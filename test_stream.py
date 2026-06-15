import urllib.request
response = urllib.request.urlopen("http://localhost:8765/api/generate-stream?type=weekly")
for line in response:
    print(line.decode('utf-8').strip())
