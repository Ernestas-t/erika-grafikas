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

    // Convert image to base64
    const buffer = Buffer.from(await photo.arrayBuffer());
    const base64Image = buffer.toString("base64");

    // Call Python API
    const pythonResponse = await fetch(
      `${process.env.VERCEL_URL ? "https://" + process.env.VERCEL_URL : "http://localhost:4321"}/api/process`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          image: base64Image,
        }),
      },
    );

    if (!pythonResponse.ok) {
      throw new Error("Python processing failed");
    }

    const result = await pythonResponse.json();

    if (!result.success) {
      throw new Error(result.error || "Processing failed");
    }

    // Save ICS content to temp file
    const tempDir = tmpdir();
    const icsFileName = result.filename || `darbo_grafikas_${Date.now()}.ics`;
    const icsPath = join(tempDir, icsFileName);

    await writeFile(icsPath, result.ics_content);

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
