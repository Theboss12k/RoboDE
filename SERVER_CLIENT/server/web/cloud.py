"""Persistent cloud deployment: one private runtime and two authenticated frontends."""
import argparse,os
import uvicorn

def main():
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=['api','ide','business']);args=parser.parse_args()
    if args.mode=='api':
        from services.api.main import create_app
        app=create_app();port=8765
    else:
        from web.gateway import create_gateway
        code=os.environ['ROBOT_IDE_ACCESS_CODE']
        app=create_gateway(upstream='http://127.0.0.1:8765',scope=args.mode,code=code)
        port=8083 if args.mode=='ide' else 8084
    uvicorn.run(app,host='127.0.0.1',port=port,workers=1)

if __name__=='__main__':main()
