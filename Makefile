up:
	docker compose up ollama

# install model
install:
	docker exec -it ollama ollama pull gemma4:e4b

# test run
test:
	curl http://localhost:8000/v1/chat/completions -d '{"model": "gemma4:e4b", "messages": [{"role": "user", "content": "write a good python function which gets two arguments and returns sum of those"}]}'