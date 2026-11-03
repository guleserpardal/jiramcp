from pathlib import Path

ROOT = Path(__file__).parents[2]


def test_dockerfile_injects_version_before_project_install() -> None:
    lines = (ROOT / "Dockerfile").read_text().splitlines()

    arg_index = lines.index("ARG VERSION")
    copy_index = lines.index("COPY . /app")
    rewrite_index = next(i for i, line in enumerate(lines) if "sed -i" in line)
    install_indices = [
        i for i, line in enumerate(lines) if "uv sync" in line and "--no-dev" in line
    ]

    assert arg_index < copy_index < rewrite_index < install_indices[-1]
    assert 'fallback-version = \\"0.0.0\\"' in lines[rewrite_index]
    assert 'fallback-version = \\"$VERSION\\"' in lines[rewrite_index]
