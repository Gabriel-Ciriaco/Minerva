"""
Script de geração do mini-corpus acadêmico de 5 arquivos usado pelos testes:
1. doc1_ementa.pdf: PDF textual com ementa de Engenharia de Software e POO
2. doc2_requisitos_tabela.pdf: PDF com requisitos e tabelas de métricas
3. doc3_slides_padroes.pptx: Apresentação com slides sobre Padrões de Projeto (GoF)
4. doc4_resumo_codigo.md: Resumo Markdown com código C++ e Java e fórmulas
5. doc5_digitalizado_sem_texto.pdf: PDF com páginas puramente em imagem (sem texto selecionável)
"""
import os
import io
from pypdf import PdfWriter
from pptx import Presentation
from pptx.util import Inches, Pt
from PIL import Image, ImageDraw, ImageFont

CORPUS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "corpus")
os.makedirs(CORPUS_DIR, exist_ok=True)

# 1. doc1_ementa.pdf (Textual em 2 páginas usando pypdf com text annotations/canvas simples)
# Como pypdf não gera layouts complexos do zero sem ReportLab, criamos páginas com stream de texto direto em PDF
def create_text_pdf(path, pages_text):
    # Formatação mínima e válida de PDF texto nativo
    pdf_content = []
    objects = []
    
    # Geramos via pypdf com imagens ou texto limpo via canvas sintético
    # Uma forma 100% pura sem dependência externa é usar o reportlab se houvesse, ou montar streams PDF mínimos:
    # Vamos gerar streams PDF padrão com comandos BT / ET
    lines_per_page = pages_text
    num_pages = len(pages_text)
    
    # Usando Pillow para criar imagem e salvar como PDF para o digitalizado,
    # e para os PDFs textuais usamos pdfminer/pypdfium ou geramos PDF sintético com fontes padrão do PDF (Helvetica)
    raw_pdf = io.BytesIO()
    # Construção de PDF texto simples
    out = (
        "%PDF-1.4\n"
        "1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n"
        "2 0 obj << /Type /Pages /Kids [" + " ".join(f"{3 + i*3} 0 R" for i in range(num_pages)) + f"] /Count {num_pages} >> endobj\n"
    )
    
    obj_id = 3
    for idx, text in enumerate(pages_text):
        # Escape parenthesis
        escaped_text = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        text_stream = (
            "BT\n"
            "/F1 12 Tf\n"
            "50 750 Td\n"
            "16 TL\n"
        )
        for line in escaped_text.split("\n"):
            esc_line = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            # encode to latin-1 for standard Type1 Helvetica
            text_stream += f"({esc_line}) '\n"
        text_stream += "ET\n"
        stream_bytes = text_stream.encode("latin-1", errors="replace")
        
        page_obj = (
            f"{obj_id} 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
            f"/Contents {obj_id+1} 0 R /Resources << /Font << /F1 {obj_id+2} 0 R >> >> >> endobj\n"
            f"{obj_id+1} 0 obj << /Length {len(stream_bytes)} >> stream\n"
        )
        out += page_obj
        raw_pdf.write(out.encode("latin-1"))
        raw_pdf.write(stream_bytes)
        out = (
            f"\nendstream\nendobj\n"
            f"{obj_id+2} 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >> endobj\n"
        )
        obj_id += 3
        
    raw_pdf.write(out.encode("latin-1"))
    xref_pos = raw_pdf.tell()
    # xref
    xref = (
        f"xref\n0 {obj_id}\n"
        "0000000000 65535 f \n"
    )
    # trailer
    trailer = (
        f"trailer << /Size {obj_id} /Root 1 0 R >>\n"
        f"startxref\n{xref_pos}\n%%EOF\n"
    )
    raw_pdf.write(trailer.encode("latin-1"))
    
    with open(path, "wb") as f:
        f.write(raw_pdf.getvalue())
    print(f"[OK] Criado: {path}")

# Gerar doc1_ementa.pdf
doc1_p1 = (
    "UNIVERSIDADE EXEMPLO - DEPARTAMENTO DE COMPUTACAO\n"
    "Curso: Ciencia da Computacao\n"
    "Disciplina: Engenharia de Software I\n"
    "Codigo: ES1-2026\n"
    "\n"
    "EMENTA OFICIAL DA DISCIPLINA:\n"
    "1. Introducao aos Processos de Software: modelo Cascata, Prototipacao e Desenvolvimento Agil.\n"
    "2. Engenharia de Requisitos: elicitacao, analise, especificacao e validacao de requisitos funcionais.\n"
    "3. Requisitos Nao-Funcionais (RNF): desempenho, seguranca, usabilidade e confiabilidade.\n"
    "4. Casos de Uso e Historias de Usuario (User Stories).\n"
    "5. Modelagem conceitual utilizando Unified Modeling Language (UML).\n"
    "Bibliografia Principal: Sommerville, Engenharia de Software, 10a Edicao."
)
doc1_p2 = (
    "Engenharia de Software I - Pagina 2\n"
    "\n"
    "CRITERIOS DE AVALIACAO E PROVAS:\n"
    "- Prova P1 (Peso 4.0): Processos de Software e Engenharia de Requisitos.\n"
    "- Prova P2 (Peso 4.0): Modelagem UML, Casos de Uso e Arquitetura de Software.\n"
    "- Projeto Pratico (Peso 2.0): Especificacao completa de um sistema real em equipe.\n"
    "\n"
    "Horario de Atendimento: Quartas-feiras das 14h as 16h no Bloco de Computacao.\n"
    "Monitoria: Tercas e Quintas das 17h as 18h no Laboratorio 3."
)
create_text_pdf(os.path.join(CORPUS_DIR, "doc1_ementa.pdf"), [doc1_p1, doc1_p2])

# Gerar doc2_requisitos_tabela.pdf
doc2_p1 = (
    "DOCUMENTO DE ESPECIFICACAO DE REQUISITOS - SISTEMA MINERVA\n"
    "Versao 1.0 - Modulo de Indexacao e Recuperacao\n"
    "\n"
    "Requisitos Funcionais:\n"
    "[RF01] O sistema deve converter arquivos PDF, PPTX e Markdown em trechos indexados.\n"
    "[RF02] O agente deve responder com citacao explicita de pagina fisica ou numero de slide.\n"
    "[RF03] O sistema deve rejeitar caminhos externos fora da pasta sources atravessando symlinks.\n"
    "\n"
    "Metricas de Qualidade e Desempenho (Requisitos Nao-Funcionais):\n"
    "Metrica               Alvo Aceitavel       Tempo Limite\n"
    "Latencia de busca     < 100 ms             250 ms\n"
    "Teto de tokens        600 tokens           800 tokens maximo\n"
    "Consumo de memoria    < 150 MB             300 MB\n"
    "Recall no top-5       >= 80%               >= 70%\n"
    "\n"
    "Formula de calculo de precisao: P = Relevantes_Recuperados / Total_Recuperados."
)
create_text_pdf(os.path.join(CORPUS_DIR, "doc2_requisitos_tabela.pdf"), [doc2_p1])

# 3. doc3_slides_padroes.pptx
prs = Presentation()
# Slide 1: Capa
slide1 = prs.slides.add_slide(prs.slide_layouts[0])
slide1.shapes.title.text = "Padroes de Projeto em POO e Engenharia de Software"
slide1.placeholders[1].text = "Prof. Exemplo - Departamento de Computação\nDesign Patterns (GoF) e Arquitetura"

# Slide 2: Padrao Singleton e Factory
slide2 = prs.slides.add_slide(prs.slide_layouts[1])
slide2.shapes.title.text = "Padroes Criacionais: Factory Method e Singleton"
body2 = slide2.shapes.placeholders[1].text_frame
body2.text = "Visao Geral dos Padroes Criacionais:"
p = body2.add_paragraph()
p.text = "- Factory Method: define uma interface para criar um objeto, deixando as subclasses decidirem."
p = body2.add_paragraph()
p.text = "- Singleton: garante que uma classe tenha apenas uma instancia no sistema e fornece ponto de acesso global."
p = body2.add_paragraph()
p.text = "- Aplicacao em C++ e Java: controle estrito de conexao de banco de dados e drivers de hardware."

# Slide 3: Padrao Strategy e Observer
slide3 = prs.slides.add_slide(prs.slide_layouts[1])
slide3.shapes.title.text = "Padroes Comportamentais: Strategy e Observer"
body3 = slide3.shapes.placeholders[1].text_frame
body3.text = "Conceitos de Acoplamento Fraco (Loose Coupling):"
p = body3.add_paragraph()
p.text = "- Strategy: encapsula algoritmos alternativos de ordenacao e busca em classes separadas."
p = body3.add_paragraph()
p.text = "- Observer: define dependencia um-para-muitos entre objetos para notificacao de eventos assincronos."
p = body3.add_paragraph()
p.text = "- Pergunta frequente de P1: Qual a diferenca entre Strategy e State? Lembre-se da intencao e mudanca de estado!"

pptx_path = os.path.join(CORPUS_DIR, "doc3_slides_padroes.pptx")
prs.save(pptx_path)
print(f"[OK] Criado: {pptx_path}")

# 4. doc4_resumo_codigo.md
doc4_content = """# Resumo de Estruturas de Dados e Orientacao a Objetos

## 1. Complexidade Assintotica e Notacao Big-O
A notacao O(n log n) e tipica de algoritmos eficientes de ordenacao como MergeSort e QuickSort.
Ja buscas em grafos ou tabelas hash possuem:
- Insercao em Tabela Hash: O(1) caso medio
- Busca em Arvore Binaria de Busca (BST): O(log n)

## 2. Exemplo de Codigo em C++: Heranca e Polimorfismo
```cpp
#include <iostream>
#include <vector>

class Veiculo {
public:
    virtual void acelerar() = 0; // Metodo puramente virtual
    virtual ~Veiculo() {}
};

class Carro : public Veiculo {
public:
    void acelerar() override {
        std::cout << "Carro acelerando com C++ e polimorfismo dinâmico." << std::endl;
    }
};
```

## 3. Conceito de Herança vs Composição
Lembre-se do principio de design: "Favoreça composição sobre herança" (Favor composition over inheritance).
A heranca gera forte acoplamento (white-box reuse), enquanto composicao permite flexibilidade dinamica (black-box reuse).
"""
doc4_path = os.path.join(CORPUS_DIR, "doc4_resumo_codigo.md")
with open(doc4_path, "w", encoding="utf-8") as f:
    f.write(doc4_content)
print(f"[OK] Criado: {doc4_path}")

# 5. doc5_digitalizado_sem_texto.pdf (Páginas puramente em imagem - escaneadas)
# Criamos uma imagem com Pillow e salvamos como PDF (sem camada textual embutida)
img1 = Image.new("RGB", (600, 800), color=(255, 255, 250))
draw1 = ImageDraw.Draw(img1)
draw1.text((50, 100), "PROVA ANTIGA DIGITALIZADA (SCANNER)", fill=(40, 40, 40))
draw1.text((50, 150), "Questao 1: Defina Coesao e Acoplamento.", fill=(60, 60, 60))
draw1.text((50, 200), "Questao 2: Implemente Singleton em Java.", fill=(60, 60, 60))
draw1.line([(40, 130), (550, 130)], fill=(150, 150, 150), width=2)

doc5_path = os.path.join(CORPUS_DIR, "doc5_digitalizado_sem_texto.pdf")
img1.save(doc5_path, "PDF", resolution=100.0)
print(f"[OK] Criado: {doc5_path}")

print("\n--- Mini-corpus de 5 arquivos gerado com sucesso! ---")
