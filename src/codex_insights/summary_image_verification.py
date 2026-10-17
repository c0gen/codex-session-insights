"""Clipboard and PNG fallback smoke checks with synthetic dashboard data only."""
from pathlib import Path


def verify_summary_image(window, images, ui, wait_for, destination, result):
    from System.Windows.Forms import Clipboard

    wait_for(lambda: window.evaluate_js("!!document.querySelector('#copy-summary-image') && !document.querySelector('#copy-summary-image').disabled"))
    window.evaluate_js("document.querySelector('#copy-summary-image').click()")
    wait_for(lambda: window.evaluate_js("document.querySelector('#toast')?.textContent === 'Image copied'"))
    def copied_image():
        image = Clipboard.GetImage()
        if image is None:
            raise AssertionError("Clipboard does not contain an image")
        try:
            size = [image.Width, image.Height]
            png = Clipboard.GetData("PNG")
            assert png is not None
            encoded = bytes(png.ToArray())
            assert encoded.startswith(b"\x89PNG\r\n\x1a\n")
            return size, encoded
        finally:
            image.Dispose()
    size, png = ui(copied_image)
    assert size == [1200, 720]
    root = Path(destination).parent
    (root / "summary-clipboard.png").write_bytes(png)
    result["checks"].append("summary image copied as 1200 × 720 PNG and bitmap clipboard formats")
    # Exercise an actual paste into WebView2, beyond inspecting clipboard formats.
    def focus():
        window.native.Show()
        window.native.Activate()
        window.native.webview.Focus()
    ui(focus)
    window.evaluate_js("""(() => {
      const target = document.createElement('div');
      target.id = 'summary-paste-check'; target.contentEditable = 'true';
      Object.assign(target.style, { position: 'fixed', top: '0', right: '0', width: '2px', height: '2px', opacity: '.01' });
      target.addEventListener('paste', event => {
        event.preventDefault();
        const file = Array.from(event.clipboardData.items).find(item => item.type.startsWith('image/'))?.getAsFile();
        if (!file) return;
        createImageBitmap(file).then(image => { window.__summaryPaste = {width:image.width,height:image.height}; image.close(); });
      });
      document.body.append(target); target.focus();
    })()""")
    from System.Windows.Forms import SendKeys
    ui(lambda: SendKeys.SendWait("^v"))
    wait_for(lambda: window.evaluate_js("window.__summaryPaste?.width === 1200 && window.__summaryPaste?.height === 720"))
    window.evaluate_js("document.querySelector('#summary-paste-check').remove()")
    result["checks"].append("summary image pastes into WebView2 as a 1200 × 720 image")

    write = images.adapter.write
    choose = images.choose
    def unavailable(_packet):
        raise RuntimeError("Injected clipboard failure for verification")
    try:
        images.adapter.write = unavailable
        window.evaluate_js("document.querySelector('#copy-summary-image').click()")
        wait_for(lambda: window.evaluate_js("!!document.querySelector('#save-summary-image')"))
        images.choose = lambda *_args: None
        window.evaluate_js("document.querySelector('#save-summary-image').click()")
        wait_for(lambda: window.evaluate_js("!document.querySelector('#save-summary-image').disabled"))
        path = root / "summary-fallback.png"
        assert not path.exists()
        images.choose = lambda *_args: str(path)
        window.evaluate_js("document.querySelector('#save-summary-image').click()")
        wait_for(lambda: path.exists())
        wait_for(lambda: window.evaluate_js("document.querySelector('#toast')?.textContent === 'Image saved'"))
        assert path.read_bytes() == png
        result["checks"].append("native PNG fallback preserves the generated card and respects save cancellation")
    finally:
        images.adapter.write, images.choose = write, choose
    before = images.preferences.read()
    images.call("summary_image_preferences", {"include_project_names": True})
    from .summary_image_preferences import SummaryImagePreferences
    assert SummaryImagePreferences(images.preferences.path).read()["include_project_names"] is True
    images.call("summary_image_preferences", before)
    result["checks"].append("image name preference persists independently of the web origin and index")
    result["summary_image"] = {"width": 1200, "height": 720, "clipboard_formats": ["PNG", "Bitmap"]}
