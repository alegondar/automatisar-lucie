---
name: openspec-triage
description: Usar SIEMPRE antes de /opsx-propose o de crear un change de OpenSpec en cualquier proyecto. Explora el proyecto, clasifica el pedido y decide si se implementa directo o si necesita propuesta.
---

# Triage previo a OpenSpec

Aplica a cualquier proyecto y stack. Seguí estos pasos en orden antes de proponer nada.

## 1. Explorar (solo lectura, obligatorio)
- Identificá el stack por los archivos de la raíz (`package.json`, `Cargo.toml`, `build.gradle*`, `pubspec.yaml`, `pyproject.toml`, etc.) y leé `README` y `AGENTS.md` si existen.
- Si existe `openspec/`: leé `openspec/project.md`, listá `openspec/specs/` (qué ya está especificado) y `openspec/changes/` (si hay un change activo).
- Si NO existe `openspec/`: no lo inicialices por tu cuenta. Tratá el pedido como directo o preguntá.
- Buscá en el código los archivos que toca el pedido y leelos antes de opinar.
- Verificá si una spec existente ya cubre el área del pedido.

## 2. Clasificar

**Directo, sin propuesta**: implementá, probá y commiteá.
- Estilos, colores, espaciados, textos, íconos, traducciones.
- Bugfix de 1-2 archivos que no cambia comportamiento documentado.
- Renombres, typos, refactors internos sin impacto externo.
- Ajustes menores de config o dependencias.

**Con propuesta (/opsx-propose)**:
- Funcionalidad nueva o cambio de comportamiento visible para el usuario.
- Cambios de modelo de datos, API, auth, pagos o integraciones externas.
- Toca 3 o más módulos, o contradice una spec de `openspec/specs/`.
- Decisión de arquitectura costosa de revertir.

**Dudoso**: hacé UNA pregunta corta al usuario. No escribas la propuesta por las dudas.

## 3. Reglas
- Un solo change activo a la vez: si hay uno abierto, avisá antes de crear otro.
- En un cambio directo, explicá en una línea por qué no lleva spec y seguí.
- La propuesta debe ser proporcional al cambio, nunca más larga que el código a escribir.
- En cambios directos, commiteá y deployá si el proyecto ya tiene deploy configurado.
- Documentación, commits y comentarios en español.
- Nunca saltees el paso 1, aunque el pedido parezca trivial.
