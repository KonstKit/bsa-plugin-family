# C4 Modeling Conventions

Use these conventions unless the user or source material requires something else.

## Core Discipline

- One diagram equals one scope, one abstraction level, and one audience need.
- Start from the system in scope and zoom only one level per diagram.
- Prefer a small set of coherent diagrams over one overloaded diagram.
- Treat PlantUML as the encoding, not the modeling method. Choose the C4 view first.

## Diagram Selection

### System Context

- Scope: one software system.
- Primary element: the software system in scope.
- Supporting elements: people and external software systems directly connected to it.
- Show: responsibilities and relationships.
- Avoid: internal containers, components, low-level technologies, and implementation detail.

### Container

- Scope: one software system.
- Show: applications, data stores, queues/topics, and direct external dependencies.
- Give every container a responsibility and a technology.
- Show inter-process protocols when they are known and useful.

### Component

- Scope: one container.
- Show: components inside that container and only the nearby externals needed for context.
- Do not decompose several containers in the same component view.
- Use this view only when internal responsibilities are well understood.

### Dynamic

- Scope: one scenario or use case.
- Reuse elements from a valid static model.
- Show only the interactions needed to explain the story.
- Number relationships only when sequence matters.

### Deployment

- Scope: one deployment environment.
- Show: deployment nodes, infrastructure nodes, and software/container instances.
- Nest nodes when the infrastructure hierarchy matters.
- Split environments if the combined view becomes noisy.

### System Landscape

- Use when the user wants a portfolio or ecosystem view rather than one central system.
- Keep the abstraction at software system level.

## Evidence Mapping

- user, actor, role, persona -> `Person` or `Person_Ext`
- external software dependency -> `System_Ext`
- internal software system in a context or landscape view -> `System`
- database as a first-class software system -> `SystemDb`
- queue/topic/broker as a first-class software system -> `SystemQueue`
- internal deployable runtime unit inside one system -> `Container`
- internal database or schema-bearing store -> `ContainerDb`
- internal queue/topic/broker -> `ContainerQueue`
- cohesive code module inside one container -> `Component`
- internal database abstraction inside a container -> `ComponentDb`
- internal queue/topic abstraction inside a container -> `ComponentQueue`
- ownership or scope grouping -> `Enterprise_Boundary`, `System_Boundary`, or `Container_Boundary`

Use `*_Ext` variants only when the external distinction is meaningful to the reader.

## Naming And Descriptions

- Give every diagram a title with type and scope.
- Name people as roles or personas unless a real individual matters architecturally.
- Name elements with domain language first and technology second.
- Give every element a short responsibility description.
- Give every container and component a technology string whenever known.
- Label every relationship with an action phrase that matches the arrow direction.
- Prefer specific labels such as `Submits payment request`, `Publishes order event`, or `Reads from and writes to` over generic `Uses`.

## Relationship Rules

- Keep relationships unidirectional by default.
- Label inter-container relationships with protocol or technology when known.
- Avoid crossing too many lines; change layout before changing the model.
- Do not draw relationships that the source does not support.
- In dynamic diagrams, show only the relationships needed for the scenario.

## AS-IS vs TO-BE

- `AS-IS`: preserve the current architecture, including awkward dependencies and interim integrations.
- `TO-BE`: model the target architecture only and mark missing facts as assumptions.
- Do not silently blend current and target state in one diagram.

## Detail Budgets

- `System Context`: roughly 5-12 primary elements
- `Container`: roughly 6-20 primary elements
- `Component`: roughly 6-20 components for one container
- `Dynamic`: roughly 4-15 interactions for one scenario
- `Deployment`: enough nodes and instances to explain runtime topology; split by environment when needed

If the result exceeds these budgets, split the output by level, container, scenario, or environment.

## Review Checklist

Check these before delivery:

- the title states diagram type and scope
- the C4 level matches the question
- the system in scope is unambiguous
- every element has a type, name, and short description
- every container and component has technology when known
- every relationship is directional and labeled
- relationship text matches arrow direction
- protocols are labeled where architecturally useful
- internal and external elements are not confused
- boundaries communicate ownership or scope clearly
- the diagram does not mix context, container, and component detail
- assumptions are surfaced explicitly
