import requests


def main():
    res = requests.post("http://localhost:8765/api/generate-stream", stream=True)
    for line in res.iter_lines():
        if line:
            print(line.decode('utf-8'))


if __name__ == "__main__":
    main()
