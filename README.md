# diagnostic.ar-training

Acá reentrenamos y evaluamos el modelo de [diagnostic.ar](https://github.com/MateAlv/diagnosticar-plataforma), que ordena los genes según los síntomas del paciente. El objetivo fue que el modelo use tres datos que antes ignoraba: el sexo, la edad y los síntomas que el paciente no tiene.

Tiene los experimentos de las cuatro fases, el protocolo de evaluación con particiones selladas y la bitácora del trabajo. Las versiones que salieron de acá se publican en [diagnostic.ar-model](https://github.com/MateAlv/diagnostic.ar-model). Los resultados en detalle están en [docs/OVERVIEW.md](docs/OVERVIEW.md) y el mapa de la documentación en [docs/INDEX.md](docs/INDEX.md).

Es parte del Trabajo Profesional de Ingeniería en Informática (FIUBA) de Mateo Alvarez, Mariano Brizuela López, Gonzalo Bustamante y Lucía Lourengo Caridade.

## Probarlo

```bash
make setup
make lint test
```

`make sources` baja cada fuente fijada en `data/sources.yaml` y verifica su sha256, salvo las que no se redistribuyen (ver abajo).

## Datos

Los pacientes reales son casos publicados de phenopacket-store (CC BY 4.0). También usa HPO, Orphanet, Mondo y Gene2Phenotype (CC BY 4.0), HGNC y ClinGen (CC0), ClinVar y MedlinePlus (dominio público), y los casos MCRD y DDD tal como los distribuye [GraPhens](https://github.com/gianluccacolangelo/GraPhens). La licencia de cada fuente está en `data/sources.yaml`.

Algunos datos son solo para uso no comercial: las tablas sacadas de GeneReviews y de papers con licencia no comercial, que citan su fuente en cada fila. Las copias completas de PanelApp y de GeneReviews y los abstracts de Europe PMC no se redistribuyen. Para reproducir esos pasos hay que bajarlos de su fuente original, y `data/sources.yaml` guarda el sha256 de cada copia.

Los pesos de GenPhenia v3.0 son de Gianlucca Colangelo y no se publican. Los tests que los necesitan se saltean.

## Licencia

GPL-3.0 para el código. Las partes adaptadas de GraPhens (`src/diagnostic_ar_training/gnn/model.py` y `src/diagnostic_ar_training/systems/genphenia_v3.py`) siguen siendo de sus autores. Los datos siguen las licencias de sus fuentes.
