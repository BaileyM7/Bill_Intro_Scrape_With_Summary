from openai import OpenAI

def getKey():
    with open("utils/key.txt", "r") as file:
        return file.readline().strip()
