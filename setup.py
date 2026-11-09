"""Require the frontend build when producing a distributable wheel."""
from pathlib import Path
from setuptools import setup
from setuptools.command.build_py import build_py


class BuildWithUI(build_py):
    def run(self):
        if not Path("src/ensembl_mcp/ui/genome-browser.html").is_file():
            raise RuntimeError("Missing MCP App build: run 'cd frontend && npm ci && npm run build' before building the Python package.")
        super().run()


setup(cmdclass={"build_py": BuildWithUI})
