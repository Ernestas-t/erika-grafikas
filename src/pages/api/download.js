import { readfile } from "fs/promises";
import { join } from "path";
import { tmpdir } from "os";

export const prerender = false;

export async function get({ request, url }) {
  try {
    const searchparams = new url(request.url).searchparams;
    const filename = searchparams.get("file");
    const istemp = searchparams.get("temp") === "true";

    if (!filename || !filename.endswith(".ics")) {
      return new response("invalid file", { status: 400 });
    }

    // read from temp directory if it's a temporary file
    const filepath = istemp
      ? join(tmpdir(), filename)
      : join(process.cwd(), filename);

    console.log("reading file from:", filepath);

    const filecontent = await readfile(filepath);

    return new response(filecontent, {
      status: 200,
      headers: {
        "content-type": "text/calendar; charset=utf-8",
        "content-disposition": `attachment; filename="${filename}"`,
        "cache-control": "no-cache",
        "x-suggested-filename": filename,
        "access-control-expose-headers": "content-disposition",
        "x-content-type-options": "nosniff",
      },
    });
  } catch (error) {
    console.error("download error:", error);
    return new response("file not found", {
      status: 404,
      headers: { "content-type": "text/plain" },
    });
  }
}
