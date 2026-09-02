declare module 'react-cytoscapejs' {
  import type { Core, ElementDefinition, LayoutOptions, Stylesheet } from 'cytoscape'
  import type { CSSProperties, ComponentType } from 'react'

  interface CytoscapeComponentProps {
    elements: ElementDefinition[]
    stylesheet?: Stylesheet[]
    layout?: LayoutOptions | object
    style?: CSSProperties
    cy?: (cy: Core) => void
  }

  const CytoscapeComponent: ComponentType<CytoscapeComponentProps>
  export default CytoscapeComponent
}