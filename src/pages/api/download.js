import { readFile } from "fs/promises";
import { join } from "path";

export const prerender = false;

export async function GET({ request, url }) {
  try {
    const searchParams = new URL(request.url).searchParams;
    const filename = searchParams.get("file");

    if (!filename || !filename.endsWith(".ics")) {
      return new Response("Invalid file", { status: 400 });
    }

    // Read the ICS file
    const filePath = join(process.cwd(), filename);
    const fileContent = await readFile(filePath);

    return new Response(fileContent, {
      status: 200,
      headers: {
        "Content-Type": "text/calendar; charset=utf-8",
        "Content-Disposition": `attachment; filename="${filename}"`,
        "Cache-Control": "no-cache",
        // Better mobile support
        "X-Suggested-Filename": filename,
        "Access-Control-Expose-Headers": "Content-Disposition",
        // Additional headers for better calendar app recognition
        "X-Content-Type-Options": "nosniff",
      },
    });
  } catch (error) {
    console.error("Download error:", error);
    return new Response("File not found", {
      status: 404,
      headers: { "Content-Type": "text/plain" },
    });
  }
}
