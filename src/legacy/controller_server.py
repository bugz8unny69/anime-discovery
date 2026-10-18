"""Start controller using centrally configured loopback address and port."""
from anime_config_runtime import get
import uvicorn

if __name__ == '__main__':
    uvicorn.run('api:app', host=get('controller.bind_host'), port=get('controller.bind_port'), log_level='info')
