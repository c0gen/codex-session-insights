"""Desktop and automation entry points."""
import argparse
import json
import os
import platform
import sys
import time
from pathlib import Path

from .ingestion import refresh
from .pricing_catalog import catalog
from .queries import dashboard
from .report import export_html
from .service import Engine
from .transfers import export_snapshot, import_snapshot


def default_directory():
    override=os.environ.get('CODEX_INSIGHTS_DATA_DIR')
    if override:
        return Path(override).expanduser()
    if platform.system()=='Darwin':
        return Path.home()/'Library'/'Application Support'/'Codex Session Insights'
    return Path(os.environ.get('LOCALAPPDATA',Path.home()/'.local'/'share'))/'Codex Session Insights'


def main(argv=None):
    parser=argparse.ArgumentParser(description='Local Codex usage dashboard and compact exporter')
    parser.add_argument('--data-dir',type=Path,default=default_directory())
    parser.add_argument('--demo',action='store_true',help='Use isolated synthetic data')
    subs=parser.add_subparsers(dest='command')
    for name in ('gui','exporter','serve'):
        sub=subs.add_parser(name)
        sub.add_argument('--port',type=int,default=0)
    scan=subs.add_parser('scan');scan.add_argument('--root',action='append');scan.add_argument('--rebuild',action='store_true')
    export=subs.add_parser('export');export.add_argument('--output',type=Path,required=True);export.add_argument('--root',action='append');export.add_argument('--label')
    imp=subs.add_parser('import');imp.add_argument('snapshot',type=Path)
    report=subs.add_parser('report');report.add_argument('--output',type=Path,required=True);report.add_argument('--include-names',action='store_true')
    subs.add_parser('catalog')
    args=parser.parse_args(argv)
    args.command=args.command or 'gui'
    directory=args.data_dir/'demo' if args.demo else args.data_dir
    engine=Engine(directory,args.demo,args.command=='exporter')
    try:
        if args.command in ('scan','export'):
            if getattr(args,'root',None):
                # Explicit roots replace default roots for this command's indexed population.
                for source in engine.store.sources():
                    if source['kind']=='folder' and source['segments']==0:
                        engine.store.forget_source(source['id'])
                for root in args.root:
                    engine.store.add_source(root)
            if not args.demo:
                result=refresh(engine.store,rebuild=getattr(args,'rebuild',False))
            else:
                result={'demo':True}
            if args.command=='export':
                result=export_snapshot(engine.store,args.output,args.label or engine.store.setting('device_label'))
        elif args.command=='import':
            result=import_snapshot(engine.store,args.snapshot)
        elif args.command=='report':
            result=export_html(dashboard(engine.store),args.output,not args.include_names)
        elif args.command=='catalog':
            result=catalog()
        else:
            from .server import start_server
            server,url=start_server(engine,getattr(args,'port',0))
            try:
                engine.start()
                if args.command=='serve':
                    print(url,flush=True)
                    while True:
                        time.sleep(.5)
                else:
                    import webview
                    class Bridge:
                        def call(self,action,args=None):
                            return engine.call(action,args)
                    engine.window=webview.create_window('Codex Session Insights',url,js_api=Bridge(),width=1500 if not engine.exporter else 1000,height=960 if not engine.exporter else 720,min_size=(850,600),background_color='#10171c')
                    webview.start(gui='edgechromium' if platform.system()=='Windows' else None)
            finally:
                server.shutdown();server.server_close()
            return 0
        print(json.dumps(result,indent=2,default=str))
        return 0
    except KeyboardInterrupt:
        return 0
    except Exception as exc:
        if args.command in ('gui','exporter'):
            # A windowed executable has no terminal: show prerequisite errors natively.
            import ctypes
            if platform.system()=='Windows':
                ctypes.windll.user32.MessageBoxW(0,str(exc)+'\n\nOn Windows, install Microsoft Edge WebView2 Runtime.','Codex Session Insights',0x10)
        if sys.stderr:
            print(str(exc),file=sys.stderr)
        return 1
    finally:
        engine.close()


if __name__=='__main__':
    raise SystemExit(main())
