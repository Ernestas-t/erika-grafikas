import { writeFile } from "fs/promises";
import { join } from "path";
import { tmpdir } from "os";

export const prerender = false;

export async function POST({ request }) {
  try {
    const formData = await request.formData();
    const photo = formData.get("photo");

    if (!photo || photo.size === 0) {
      return new Response(JSON.stringify({ error: "No photo uploaded" }), {
        status: 400,
        headers: { "Content-Type": "application/json" },
      });
    }

    console.log("Processing photo:", photo.name, "Size:", photo.size);

    // Convert image to base64
    const buffer = Buffer.from(await photo.arrayBuffer());
    const base64Image = buffer.toString("base64");

    console.log("Calling Python API...");

    // Get the base URL
    const baseUrl = process.env.VERCEL_URL
      ? `https://${process.env.VERCEL_URL}`
      : "http://localhost:4321";

    // Call Python API
    const pythonResponse = await fetch(`${baseUrl}/api/process`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        image: base64Image,
      }),
    });

    console.log("Python API response status:", pythonResponse.status);

    if (!pythonResponse.ok) {
      const errorText = await pythonResponse.text();
      console.error("Python API error:", errorText);
      throw new Error(`Python processing failed: ${errorText}`);
    }

    const result = await pythonResponse.json();
    console.log("Python API result:", result.success);

    if (!result.success) {
      throw new Error(result.error || "Processing failed");
    }

    // Save ICS content to temp file
    const tempDir = tmpdir();
    const icsFileName = result.filename || `darbo_grafikas_${Date.now()}.ics`;
    const icsPath = join(tempDir, icsFileName);

    await writeFile(icsPath, result.ics_content);
    console.log("ICS file saved to:", icsPath);

    return new Response(
      JSON.stringify({
        success: true,
        downloadUrl: `/api/download?file=${icsFileName}&temp=true`,
        filename: icsFileName,
      }),
      {
        status: 200,
        headers: { "Content-Type": "application/json" },
      },
    );
  } catch (error) {
    console.error("Upload error:", error);
    return new Response(
      JSON.stringify({
        error: "Upload failed",
        details: error.message,
      }),
      {
        status: 500,
        headers: { "Content-Type": "application/json" },
      },
    );
  }
}
