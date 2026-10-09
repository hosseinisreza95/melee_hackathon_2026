import subprocess,sys
def test_starter_data_validates():
 r=subprocess.run([sys.executable,"scripts/validate_data.py"],capture_output=True,text=True)
 assert r.returncode==0,r.stdout+r.stderr
