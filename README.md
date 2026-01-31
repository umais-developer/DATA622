Quarto CLI: Download and install it from the official Quarto website:https://quarto.org/docs/get-started/

quarto install tinytex   

uv pip install jupyter 

uv add PyYAML jupyter ipykernel


uv add ipykernel matplotlib pandas    


uv run quarto render report.qmd --to pdf

uv add graphviz

quarto install tool chromium

uv add numpy scikit-learn  

uv run quarto render lab1.qmd --to html  

uv add ipywidgets  

quarto clean        

uv run quarto clean

quarto preview c:/CunyCourses/Data622/Week1/Lab1/report.qmd --no-browser --no-watch-input

  
