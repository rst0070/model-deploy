qwen3_5-0_8b:
	docker compose --env-file .env up -d vllm-qwen3_5-0_8b

gemma3-4b-it:
	docker compose --env-file .env up -d vllm-gemma3-4b-it

up:
	docker compose up ollama