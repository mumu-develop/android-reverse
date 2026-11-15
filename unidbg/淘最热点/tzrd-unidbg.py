import subprocess

cmd = "java -jar TzrdSign.jar"
res = subprocess.check_output(cmd, shell=True,text=True)
print(res)