"""Limited business-app gateway. Run from PROJECT: node scripts/python.mjs -m BUSINESS_APP.server."""
import argparse
import os
from web.gateway import create_gateway as _create_gateway


def create_gateway(upstream='http://127.0.0.1:8765',dist=None,code=None):
    return _create_gateway(upstream,dist,code,scope='business')

if __name__=='__main__':
    import uvicorn
    parser=argparse.ArgumentParser();parser.add_argument('--host',default='127.0.0.1');parser.add_argument('--port',default=8080,type=int);args=parser.parse_args()
    if args.host not in {'127.0.0.1','localhost','::1'} and not os.getenv('BUSINESS_ACCESS_CODE'):parser.error('Set BUSINESS_ACCESS_CODE for shared access. Use HTTPS for phone camera/microphone support.')
    uvicorn.run(create_gateway(os.getenv('ROBOT_IDE_UPSTREAM','http://127.0.0.1:8765')),host=args.host,port=args.port)
