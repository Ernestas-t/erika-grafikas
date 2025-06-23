// src/pages/api/upload.js
import { writeFile, readdir } from "fs/promises";
import { join } from "path";
import { exec } from "child_process";
import { promisify } from "util";
import { tmpdir } from "os";

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

    // Use /tmp directory which is writable in serverless environments
    const tempDir = tmpdir();
    const imageFileName = `grafikas_${Date.now()}.jpg`;
    const imagePath = join(tempDir, imageFileName);

    // Save uploaded file
    const buffer = Buffer.from(await photo.arrayBuffer());
    await writeFile(imagePath, buffer);

    console.log(`Saved uploaded file to: ${imagePath}`);

    // Create a temporary Python script that uses the correct paths
    const pythonScript = `
import sys
import os
sys.path.append('${process.cwd()}')

# Change working directory to temp
os.chdir('${tempDir}')

# Copy main.py logic but use temp directory
import re
from datetime import datetime
import cv2
import numpy as np
import pytesseract
import pytz
from icalendar import Calendar, Event

# Set the image path to our temp file
IMAGE_PATH = "${imagePath}"
OUTPUT_TXT = "erika_schedule.txt"
DEBUG_GRID = "debug_grid.png"
DEBUG_CELLS = "debug_cells.png"
NUM_DAYS = 31
TARGET_ROW = 3

# Your Python script logic here (copy from main.py)
# ... [rest of your Python code]
`;

    const scriptPath = join(tempDir, "temp_script.py");
    await writeFile(scriptPath, pythonScript);

    // Run Python script in temp directory
    try {
      const { stdout, stderr } = await execAsync(`python3 ${scriptPath}`, {
        cwd: tempDir,
        env: { ...process.env, PYTHONPATH: process.cwd() },
      });

      console.log("Python output:", stdout);
      if (stderr) console.log("Python stderr:", stderr);

      // Check if ICS file was created in temp directory
      const files = await readdir(tempDir);
      const icsFile = files.find((file) => file.endsWith(".ics"));

      if (icsFile) {
        return new Response(
          JSON.stringify({
            success: true,
            downloadUrl: `/api/download?file=${icsFile}&temp=true`,
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
