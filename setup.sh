#!/usr/bin/env bash
set -e

pip install -r requirements.txt

python -m spacy download en_core_web_sm || pip install https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.7.1/en_core_web_sm-3.7.1-py3-none-any.whl

python -m nltk.downloader words
python -m nltk.downloader stopwords
