import CytoscapeComponent from 'react-cytoscapejs'
import type { CytoscapeElement } from '../types'

interface Props {
  elements: { nodes: CytoscapeElement[]; edges: CytoscapeElement[] }
  rootCauseNode: string
  secondaryNodes: string[]
}

// ノード状態を data 属性として付与し CSS セレクターでスタイリング
function tagElements(
  elements: { nodes: CytoscapeElement[]; edges: CytoscapeElement[] },
  rootCauseNode: string,
  secondaryNodes: string[],
) {
  const secSet = new Set(secondaryNodes)
  const nodes = elements.nodes.map((n) => ({
    data: {
      ...n.data,
      nodeType:
        n.data.id === rootCauseNode
          ? 'root'
          : secSet.has(n.data.id)
            ? 'secondary'
            : 'normal',
    },
  }))
  return [...nodes, ...elements.edges]
}

const STYLESHEET = [
  {
    selector: 'node',
    style: {
      'background-color': '#93c5fd',
      label: 'data(id)',
      color: '#1e3a5f',
      'font-size': 11,
      'text-valign': 'bottom' as const,
      'text-margin-y': 6,
      width: 42,
      height: 42,
    },
  },
  {
    selector: 'node[nodeType = "root"]',
    style: { 'background-color': '#ef4444' },
  },
  {
    selector: 'node[nodeType = "secondary"]',
    style: { 'background-color': '#f59e0b' },
  },
  {
    selector: 'edge',
    style: {
      width: 2,
      'line-color': '#94a3b8',
      'target-arrow-color': '#94a3b8',
      'target-arrow-shape': 'triangle' as const,
      'curve-style': 'bezier' as const,
    },
  },
]

export function TopologyMap({ elements, rootCauseNode, secondaryNodes }: Props) {
  const allElements = tagElements(elements, rootCauseNode, secondaryNodes)
  return (
    <CytoscapeComponent
      elements={allElements}
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      stylesheet={STYLESHEET as any}
      layout={{ name: 'breadthfirst', directed: true } as object}
      style={{ width: '100%', height: '400px', background: '#f8fafc' }}
    />
  )
}
