"""Process recorder loaded by sitecustomize; no compiler argument rewriting."""
import json
import os
import subprocess
import time
import uuid
from pathlib import Path

def install():
    target = os.environ.get('REPRO_EVENTS')
    if not target:
        return
    def emit(record):
        record.update(time_ns=time.time_ns(), observer_pid=os.getpid())
        data=(json.dumps(record, default=str, ensure_ascii=True)+'\n').encode()
        fd=os.open(target, os.O_WRONLY|os.O_CREAT|os.O_APPEND, 0o600)
        try: os.write(fd,data)
        finally: os.close(fd)
    original=subprocess.Popen
    class Recorded(original):
        def __init__(self,*args,**kwargs):
            self.event_id=uuid.uuid4().hex
            self.recorded_exit=False
            emit(dict(event='spawn',id=self.event_id,argv=args[0] if args else kwargs.get('args'),
                      cwd=str(kwargs.get('cwd') or os.getcwd()),shell=kwargs.get('shell',False)))
            try: super().__init__(*args,**kwargs)
            except BaseException as exc:
                emit(dict(event='spawn_error',id=self.event_id,error=repr(exc)))
                raise
        def wait(self,*args,**kwargs):
            result=super().wait(*args,**kwargs)
            if not self.recorded_exit:
                self.recorded_exit=True
                emit(dict(event='exit',id=self.event_id,child_pid=self.pid,returncode=result))
            return result
    subprocess.Popen=Recorded
