import { writeFile } from "fs/promises";
import { join } from "path";
import { exec } from "child_process";
import { promisify } from "util";

const execAsync = promisify(exec);

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

    // Save uploaded file as grafikas.jpg (what your Python script expects)
    const buffer = Buffer.from(await photo.arrayBuffer());
    const filePath = join(process.cwd(), "grafikas.jpg");
    await writeFile(filePath, buffer);

    console.log(`Saved uploaded file to: ${filePath}`);

    // Run your Python script with uv (Railway supports this!)
    try {
      const { stdout, stderr } = await execAsync("uv run python main.py", {
        cwd: process.cwd(),
      });

      console.log("Python output:", stdout);
      if (stderr) console.log("Python stderr:", stderr);

      // Check if ICS file was created
      const { readdirSync } = await import("fs");
      const files = readdirSync(process.cwd());
      const icsFile = files.find((file) => file.endsWith(".ics"));

      if (icsFile) {
        return new Response(
          JSON.stringify({
            success: true,
            downloadUrl: `/api/download?file=${icsFile}`,
            filename: icsFile,
          }),
          {
            status: 200,
            headers: { "Content-Type": "application/json" },
          },
        );
      } else {
        throw new Error("ICS file not generated");
      }
    } catch (pythonError) {
      console.error("Python script error:", pythonError);
      return new Response(
        JSON.stringify({
          error: "Failed to process schedule",
          details: pythonError.message,
        }),
        {
          status: 500,
          headers: { "Content-Type": "application/json" },
        },
      );
    }
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
