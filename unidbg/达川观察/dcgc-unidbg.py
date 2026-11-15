import subprocess
import uuid
import time

account = str(uuid.uuid4())
ts = str(int(time.time() * 1000))
cmd = ["java", "-jar", "DachuanSign.jar", account, "", ts]
res = subprocess.check_output(cmd, shell=True,text=True)
print(res)