import subprocess
import re
import sys

proc = subprocess.Popen(['cloudflared.exe', 'tunnel', '--url', 'http://127.0.0.1:8088'], stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='ignore')

print("==========================================================")
print(" [ PASSION MATE - Cloudflare Tunnel ] ")
print("==========================================================")
print("Fetching secure external address. Please wait...")

found = False
for line in proc.stderr:
    if not found and 'trycloudflare.com' in line:
        match = re.search(r'(https://[a-zA-Z0-9-]+\.trycloudflare\.com)', line)
        if match:
            url = match.group(1)
            
            with open('latest_url.txt', 'w', encoding='utf-8') as f:
                f.write(url)
                
            print("\n")
            print("==========================================================")
            print("Tunnel successfully opened!")
            print("Copy the address below to connect from outside:")
            print("")
            print(f"      >>>  {url}  <<<")
            print("")
            print("==========================================================")
            print("\nWARNING: If you close this black window, the connection will be blocked.")
            found = True
