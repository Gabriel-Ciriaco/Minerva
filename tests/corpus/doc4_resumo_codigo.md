# Resumo de Estruturas de Dados e Orientacao a Objetos

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
