from setuptools import setup, find_packages

setup(
    name="kubeqa-shield",
    version="0.1.0",
    packages=find_packages(),
    entry_points={
        "console_scripts": [
            "kubeqa=kubeqa.cli:main",
        ],
    },
    install_requires=[
        "httpx>=0.27.0",
        "pyyaml>=6.0",
        "kopf>=1.37.0",
        "playwright>=1.40.0",
        "pytest>=8.0.0",
    ],
)
