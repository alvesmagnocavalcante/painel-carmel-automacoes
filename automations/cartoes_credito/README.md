# Conferência de cartões de crédito

No portal, acesse **Cartões de crédito**. A colaboradora exporta a fatura XLSX
no Itaú e usa **Carregar fatura XLSX**. O portal lê as transações e consulta
os lançamentos do CMFlex no período correspondente. Se necessário, o período e
a empresa podem ser corrigidos em **Busca no CMFlex**. A consulta usa a view
`cmflex.pagamentos_cartao_credito` e a contagem real dos anexos em
`cmflex.documentos_anexos`, vinculados por `iddocumentocapcarbase` e `fkempresa`.
O conteúdo (`bytea`) é carregado somente ao abrir um lançamento, com o mesmo
visualizador e limite de 20 MB usados no Borderô.

Abra cada item da fatura. A tela sugere lançamentos internos da mesma empresa
e com o mesmo valor, ordenados pela data mais próxima. Para uma compra, compare
o documento antes de marcar **Conferido**; sem correspondência, registre
**Pendente** com motivo quando precisar investigar. Anuidades, IOF e demais
encargos identificados na fatura podem ser marcados manualmente como
**Encargo conferido**, sem vínculo com lançamento interno. Essa opção não é
oferecida para compras comuns. Nenhuma correspondência ou encargo é confirmado
automaticamente. **Baixar resultado** gera um novo XLSX; se ainda houver itens
sem revisão, o botão indica **Baixar parcial**. A fatura original não é alterada.
As marcações valem apenas na sessão atual e não são gravadas no CMFlex.

O filtro da lista permite ver todos os itens, apenas os que têm lançamento com
mesmo valor na empresa consultada, os sem lançamento encontrado nessa busca ou
os encargos. Ele não altera as marcações nem o XLSX exportado. "Sem lançamento"
não confirma ausência no CMFlex: depende da empresa e do período consultados.

Os anexos da consulta são PDFs do **CMFlex**, não a fatura do **Itaú** descrita no
procedimento `CONFERÊNCIA DOS CARTÕES DE CRÉDITO.docx`. O portal não solicita
credenciais bancárias nem importa PDF de fatura. O XLSX enviado é limitado a
5 MB, lido em diretório temporário e apagado após a leitura. As transações
permanecem em memória durante a sessão para revisão e exportação. A importação
foi validada com o formato da fatura fornecida; alterações no layout do Itaú
devem ser testadas antes de usar a conferência.
