# Build the preprint PDF (pdflatex + bibtex). `make data` reruns the experiments first.
PY ?= python3

ntpstats-preprint-2026.pdf: main.tex refs.bib tables/*.tex figures/*.pdf
	pdflatex -interaction=nonstopmode -halt-on-error main.tex >/dev/null
	bibtex main >/dev/null
	pdflatex -interaction=nonstopmode -halt-on-error main.tex >/dev/null
	pdflatex -interaction=nonstopmode -halt-on-error main.tex >/dev/null
	pdflatex -interaction=nonstopmode -halt-on-error main.tex | grep -E "Warning|Output written" || true
	cp main.pdf $@

data:
	$(PY) experiments.py
	$(PY) make_tables.py

clean:
	rm -f main.aux main.bbl main.blg main.log main.out main.pdf

.PHONY: data clean
