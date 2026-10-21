/** Shared native/browser transport for locally rendered summary and exhibit PNGs. */
export const MAX_IMAGE_BYTES = 2 * 1024 * 1024;
export const pngBase64 = (blob: Blob): Promise<string> =>
  new Promise((resolve, reject) => {
    if (blob.size > MAX_IMAGE_BYTES) {
      reject(new Error("Image exceeds the 2 MiB limit"));
      return;
    }
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",")[1]);
    reader.onerror = () => reject(new Error("Could not read image"));
    reader.readAsDataURL(blob);
  });
export async function copyPng(image: Promise<Blob>) {
  if (window.pywebview?.api) {
    const result = (await window.pywebview.api.call("copy_summary_image", {
      png_base64: await pngBase64(await image),
    })) as { status: string };
    if (result?.status !== "copied") throw new Error("Clipboard write failed");
  } else {
    if (!navigator.clipboard?.write || typeof ClipboardItem === "undefined")
      throw new Error("Image clipboard unavailable");
    // Keep the browser's user activation while rendering/encoding completes.
    await navigator.clipboard.write([
      new ClipboardItem({ "image/png": image }),
    ]);
  }
}
export async function savePng(
  blob: Blob,
  filename: string,
): Promise<"saved" | "cancelled" | "downloaded"> {
  if (blob.size > MAX_IMAGE_BYTES)
    throw new Error("Image exceeds the 2 MiB limit");
  if (window.pywebview?.api) {
    const result = (await window.pywebview.api.call("save_summary_image", {
      png_base64: await pngBase64(blob),
      filename,
    })) as { status: string };
    if (result?.status === "cancelled") return "cancelled";
    if (result?.status !== "saved") throw new Error("Image save failed");
    return "saved";
  }
  const url = URL.createObjectURL(blob),
    a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  return "downloaded";
}
