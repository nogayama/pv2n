# Development



## Install




```sh
git clone git@github.com:nogayama/pv2n.git
cd pv2n

python -m pip install -e '.[dev]'
```



## Code Format

```sh
yapf -ir src
```



## Appendix



### Python env


1. Prepare virtual Python  environment

```sh
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
```
