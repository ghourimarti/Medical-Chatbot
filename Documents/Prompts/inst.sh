uv init
uv venv

source .venv/Scripts/activate

# add dependencie in pyproject.toml than
uv sync

# to add dev dependencies as well
uv sync --extra dev

make up

docker compose ps