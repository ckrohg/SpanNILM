import { useEffect, useRef } from 'react'
import {
  forceSimulation,
  forceCollide,
  forceCenter,
  forceX,
  forceY,
  type SimulationNodeDatum,
} from 'd3-force'
import type { DeviceCluster } from '../lib/api'

const CATEGORY_COLORS: Record<string, string> = {
  hvac: '#3b82f6',
  kitchen: '#22c55e',
  water: '#06b6d4',
  laundry: '#a855f7',
  ev: '#f59e0b',
  lighting: '#eab308',
  other: '#6b7280',
}

function getCategoryColor(device: DeviceCluster): string {
  const category = device.matches[0]?.category?.toLowerCase() || 'other'
  for (const [key, color] of Object.entries(CATEGORY_COLORS)) {
    if (category.includes(key)) return color
  }
  return CATEGORY_COLORS.other
}

function getDeviceName(device: DeviceCluster): string {
  return device.label || device.matches[0]?.device_name || `Unknown #${device.cluster_id}`
}

interface BubbleNode extends SimulationNodeDatum {
  device: DeviceCluster
  r: number
  color: string
  name: string
}

export default function BubbleView({ devices }: { devices: DeviceCluster[] }) {
  const svgRef = useRef<SVGSVGElement>(null)
  const nodesRef = useRef<BubbleNode[]>([])

  useEffect(() => {
    const svg = svgRef.current
    if (!svg) return

    const width = svg.clientWidth || 600
    const height = svg.clientHeight || 400

    // Only include devices that are currently on or were recently observed
    const activeDevices = devices.filter((d) => d.is_on || d.observation_count >= 2)

    const nodes: BubbleNode[] = activeDevices.map((device) => {
      const power = device.is_on ? device.current_power_w : device.mean_power_w
      return {
        device,
        r: Math.max(20, Math.sqrt(power) * 1.5),
        color: getCategoryColor(device),
        name: getDeviceName(device),
      }
    })

    nodesRef.current = nodes

    const simulation = forceSimulation(nodes)
      .force('center', forceCenter(width / 2, height / 2))
      .force('collide', forceCollide<BubbleNode>((d) => d.r + 4).strength(0.8))
      .force('x', forceX(width / 2).strength(0.05))
      .force('y', forceY(height / 2).strength(0.05))
      .on('tick', () => {
        // Clamp positions within bounds
        for (const node of nodes) {
          node.x = Math.max(node.r, Math.min(width - node.r, node.x || width / 2))
          node.y = Math.max(node.r, Math.min(height - node.r, node.y || height / 2))
        }
        renderBubbles(svg, nodes, width, height)
      })

    return () => {
      simulation.stop()
    }
  }, [devices])

  return (
    <svg
      ref={svgRef}
      className="w-full h-80 rounded-xl bg-gray-900/50 border border-gray-800"
    />
  )
}

function renderBubbles(
  svg: SVGSVGElement,
  nodes: BubbleNode[],
  _width: number,
  _height: number
) {
  // Clear existing
  while (svg.firstChild) svg.removeChild(svg.firstChild)

  for (const node of nodes) {
    const isOn = node.device.is_on
    const x = node.x || 0
    const y = node.y || 0

    // Glow effect for active devices
    if (isOn) {
      const glow = document.createElementNS('http://www.w3.org/2000/svg', 'circle')
      glow.setAttribute('cx', String(x))
      glow.setAttribute('cy', String(y))
      glow.setAttribute('r', String(node.r + 6))
      glow.setAttribute('fill', 'none')
      glow.setAttribute('stroke', node.color)
      glow.setAttribute('stroke-width', '2')
      glow.setAttribute('opacity', '0.3')
      svg.appendChild(glow)
    }

    // Main circle
    const circle = document.createElementNS('http://www.w3.org/2000/svg', 'circle')
    circle.setAttribute('cx', String(x))
    circle.setAttribute('cy', String(y))
    circle.setAttribute('r', String(node.r))
    circle.setAttribute('fill', isOn ? node.color : 'transparent')
    circle.setAttribute('stroke', node.color)
    circle.setAttribute('stroke-width', isOn ? '2' : '1.5')
    circle.setAttribute('opacity', isOn ? '0.85' : '0.35')
    svg.appendChild(circle)

    // Label
    const text = document.createElementNS('http://www.w3.org/2000/svg', 'text')
    text.setAttribute('x', String(x))
    text.setAttribute('y', String(y - 6))
    text.setAttribute('text-anchor', 'middle')
    text.setAttribute('fill', 'white')
    text.setAttribute('font-size', node.r > 35 ? '11' : '9')
    text.setAttribute('font-weight', '500')
    text.textContent = node.name.length > 12 ? node.name.slice(0, 10) + '..' : node.name
    svg.appendChild(text)

    // Power label
    const powerText = document.createElementNS('http://www.w3.org/2000/svg', 'text')
    powerText.setAttribute('x', String(x))
    powerText.setAttribute('y', String(y + 10))
    powerText.setAttribute('text-anchor', 'middle')
    powerText.setAttribute('fill', 'rgba(255,255,255,0.7)')
    powerText.setAttribute('font-size', node.r > 35 ? '10' : '8')
    const power = isOn ? node.device.current_power_w : node.device.mean_power_w
    powerText.textContent = power >= 1000 ? `${(power / 1000).toFixed(1)}kW` : `${Math.round(power)}W`
    svg.appendChild(powerText)
  }
}
