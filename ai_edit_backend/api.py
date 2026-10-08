from retouch_backend.api import RetouchAPI
from .service import AIEditService

class AIEditAPI(RetouchAPI):
    request_limit=8*1024*1024
    def __init__(self,token,studio):super().__init__(token,studio,AIEditService())
    def get(self,handler,path):
        return super().get(handler,path.replace('/api/ai-edit/','/api/retouch/',1)) if path.startswith('/api/ai-edit/') else False
    def post(self,handler,path):
        if not path.startswith('/api/ai-edit/'):return False
        # Shared upload/result/auth contract, independent documents and model instances.
        return super().post(handler,path.replace('/api/ai-edit/','/api/retouch/',1))
