"""Desktop and automation entry points."""
import argparse
import json
import os
import platform
import time
from pathlib import Path

from .ingestion import refresh
from .pricing_catalog import catalog
from .queries import dashboard
from .report import export_html
from .service import Engine
from .transfers import import_snapshot
from .snapshot_export import export_usage
from .paths import default_directory


def main(argv=None):
    parser=argparse.ArgumentParser(description='Local Codex usage dashboard and compact exporter')
    parser.add_argument('--data-dir',type=Path,default=default_directory())
    parser.add_argument('--demo',action='store_true',help='Use isolated synthetic data')
    parser.add_argument('--diagnose',action='store_true',help='Check native startup prerequisites without scanning')
    parser.add_argument('--allowance-smoke-result',type=Path,help=argparse.SUPPRESS)
    subs=parser.add_subparsers(dest='command')
    for name in ('gui','exporter','serve'):
        sub=subs.add_parser(name)
        sub.add_argument('--port',type=int,default=0)
        if name != 'serve':
            sub.add_argument('--smoke-result',type=Path,help=argparse.SUPPRESS)
    scan=subs.add_parser('scan');scan.add_argument('--root',action='append');scan.add_argument('--rebuild',action='store_true')
    export=subs.add_parser('export');export.add_argument('--output',type=Path,required=True);export.add_argument('--root',action='append');export.add_argument('--label')
    imp=subs.add_parser('import');imp.add_argument('snapshot',type=Path)
    report=subs.add_parser('report');report.add_argument('--output',type=Path,required=True);report.add_argument('--include-names',action='store_true')
    subs.add_parser('catalog')
    legacy=subs.add_parser('diagnose-antigravity-legacy', help='Retired: encrypted archive collection is disabled')
    legacy.add_argument('--root', type=Path, required=True)
    legacy.add_argument('--profile', type=Path, required=True)
    legacy.add_argument('--reader', type=Path)
    legacy.add_argument('--output', type=Path)
    args=parser.parse_args(argv)
    args.command=args.command or 'gui'
    if args.command == 'diagnose-antigravity-legacy':
        print(json.dumps({'status': 'disabled', 'diagnostic': 'legacy_collection_disabled',
                          'detail': 'Use documented public transcripts and official hooks. Existing indexed history is retained.'}))
        return 2
    if args.allowance_smoke_result:
        from .allowance_verification import verify_allowance
        return 0 if verify_allowance(args.allowance_smoke_result)['ok'] else 1
    if args.diagnose:
        from .desktop import diagnose
        result=diagnose()
        print(json.dumps(result,indent=2))
        return 0 if result['ok'] else 1
    directory=args.data_dir/'demo' if args.demo else args.data_dir
    instance = None
    if (args.command == 'gui' and platform.system() == 'Windows'
            and not getattr(args, 'smoke_result', None) and not os.environ.get('CODEX_INSIGHTS_SMOKE_RESULT')):
        from .single_instance import SingleInstance
        instance = SingleInstance(directory)
        if not instance.owner:
            instance.close()
            return 0
    engine = None
    try:
        engine=Engine(directory,args.demo,args.command=='exporter',
                      defer_projection=args.command in ('gui', 'exporter', 'serve'))
        if args.command in ('scan','export'):
            if getattr(args,'root',None):
                # Explicit roots replace default roots for this command's indexed population.
                for source in engine.store.sources():
                    if source['kind']=='folder' and source['segments']==0:
                        engine.store.forget_source(source['id'])
                for root in args.root:
                    engine.store.add_source(root)
            if args.command == 'export':
                result=export_usage(engine.store,args.output,args.label or engine.store.setting('device_label'))
            elif not args.demo:
                result=refresh(engine.store,rebuild=getattr(args,'rebuild',False))
            else:
                result={'demo':True}
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
                if args.command=='serve':
                    engine.start()
                    print(url,flush=True)
                    while True:
                        time.sleep(.5)
                else:
                    from .desktop import run_desktop
                    run_desktop(engine,url,getattr(args,'smoke_result',None),instance)
            finally:
                server.shutdown();server.server_close()
            return 0
        print(json.dumps(result,indent=2,default=str))
        return 0
    except KeyboardInterrupt:
        return 0
    finally:
        try:
            if engine:
                engine.close()
        finally:
            if instance:
                instance.close()


if __name__=='__main__':
    raise SystemExit(main())
