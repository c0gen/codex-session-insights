"""Synthetic account rows in the native demo widget; never opens a connection."""


def verify_account_widget(controller, widget, ui, wait_for, result, fits):
    initial_zoom = ui(lambda: float(widget.native.webview.ZoomFactor))
    initial_scale = widget.evaluate_js('devicePixelRatio')
    widget.evaluate_js("""window.__accountWidgetCall = window.pywebview.api.call;
      window.__accountWidgetCount = 1;
      window.pywebview.api.call = async (action, args) => {
        const data = await window.__accountWidgetCall(action, args);
        if (action === 'widget_summary') {
          const now = Math.floor(Date.now() / 1000);
          const accounts = Array.from({length:window.__accountWidgetCount}, (_, i) => ({
            id: String(i), label: i === 0 ? 'A deliberately long account label that wraps' : 'Account ' + (i + 1),
            allowance: {enabled:true, allowed:true, status:'available', refreshing:false, stale:false,
              last_success_at:now, error:null, buckets:[{id:'codex',name:'Codex',windows:[
                {id:'primary',remaining_percent:75,window_duration_mins:300,resets_at:now+3600},
                {id:'secondary',remaining_percent:50,window_duration_mins:10080,resets_at:now+86400}
              ]}], reset_credits:{available_count:3,details_complete:false,credits:[
                {id:'credit',status:'available',expiration:'dated',expires_at:now+3600}
              ]}}
          }));
          data.accounts = {allowed:true,enabled:true,accounts};
          data.desktop.preferences = {...data.desktop.preferences,show_usage_remaining:true,
            widget_account_ids:accounts.map(account => account.id)};
        }
        return data;
      };
      document.dispatchEvent(new Event('visibilitychange'));""")
    layouts = []
    try:
        wait_for(lambda: widget.evaluate_js("document.querySelectorAll('.widget-account').length") == 1)
        wait_for(fits)
        baseline = ui(lambda: (widget.native.Top, widget.native.Bottom, widget.native.Height))
        widget.evaluate_js("document.querySelector('.widget-details-toggle').click()")
        wait_for(lambda: widget.evaluate_js("document.querySelector('#widget-details').getBoundingClientRect().height") == 0)
        wait_for(fits)
        wait_for(lambda: ui(lambda: widget.native.Height) < baseline[2] - 40)
        assert abs(ui(lambda: widget.native.Bottom) - baseline[1]) <= 1
        assert ui(lambda: widget.native.Top) > baseline[0]
        widget.evaluate_js("document.querySelector('.widget-details-toggle').click()")
        wait_for(lambda: widget.evaluate_js("document.querySelector('#widget-details').getBoundingClientRect().height") > 70)
        wait_for(lambda: abs(ui(lambda: widget.native.Height) - baseline[2]) <= 1)
        assert abs(ui(lambda: widget.native.Bottom) - baseline[1]) <= 1
        result['checks'].append('details collapse to usage only and slide upward on expansion with the native bottom edge anchored')
        widget.evaluate_js("window.__accountWidgetCount = 12; document.dispatchEvent(new Event('visibilitychange'))")
        wait_for(lambda: widget.evaluate_js("document.querySelectorAll('.widget-account').length") == 12)
        for scale in (1, 1.25, 2):
            ui(lambda: setattr(widget.native.webview, 'ZoomFactor', initial_zoom * scale / initial_scale))
            wait_for(lambda: abs(widget.evaluate_js('devicePixelRatio') - scale) < .02)
            # WebView changes its scale before the asynchronous native layout
            # bridge has resized the window. A too-wide old window still fits.
            wait_for(lambda: abs(widget.evaluate_js('innerWidth') - 240) <= 2)
            wait_for(fits)
            wait_for(lambda: widget.evaluate_js("""(() => {
              const list = document.querySelector('#widget-scroll');
              return list.clientHeight > 0 && list.scrollHeight > list.clientHeight;
            })()"""))
            assert ui(lambda: controller.native.Screen.FromControl(widget.native).WorkingArea.Contains(widget.native.Bounds))
            assert widget.evaluate_js("document.querySelectorAll('tbody tr').length") == 3
            layout = widget.evaluate_js("({width:innerWidth,height:innerHeight,scale:devicePixelRatio})")
            assert abs(layout['width'] - 240) <= 2
            layouts.append(layout)
        widget.evaluate_js("document.querySelector('#widget-scroll').scrollTop = 100000")
        assert widget.evaluate_js("document.querySelector('#widget-scroll').scrollTop > 0")
        from .widget_resize_verification import verify_widget_resize
        verify_widget_resize(controller, widget, ui, wait_for, result, fits)
    finally:
        widget.evaluate_js("window.pywebview.api.call = window.__accountWidgetCall; document.dispatchEvent(new Event('visibilitychange'))")
        ui(lambda: setattr(widget.native.webview, 'ZoomFactor', initial_zoom))
    wait_for(lambda: widget.evaluate_js("document.querySelector('#widget-allowance').hidden"))
    wait_for(fits)
    result['widget_account_scales'] = layouts
    result['checks'].append('12 account rows, long labels and scrolling fit the native monitor at 100/125/200% scaling; original totals and width preserved')
