/** Vue Line Waves must reuse its renderer and release every owned resource on unmount. */
import { mount } from '@vue/test-utils'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import LineWaves from '@/components/common/LineWaves.vue'

const gpu = vi.hoisted(() => ({
  render: vi.fn(),
  size: vi.fn(),
  lose: vi.fn(),
  geometryRemove: vi.fn(),
  programRemove: vi.fn(),
  uniforms: {} as Record<string, { value: unknown }>,
}))
vi.mock('ogl', () => ({
  Renderer: class {
    gl = {
      canvas: document.createElement('canvas'),
      clearColor: vi.fn(),
      getExtension: () => ({ loseContext: gpu.lose }),
    }
    setSize = gpu.size
    render = gpu.render
  },
  Program: class {
    uniforms: typeof gpu.uniforms
    constructor(_gl: unknown, config: { uniforms: typeof gpu.uniforms }) {
      this.uniforms = config.uniforms
      gpu.uniforms = this.uniforms
    }
    remove = gpu.programRemove
  },
  Triangle: class {
    remove = gpu.geometryRemove
  },
  Mesh: class {},
}))

beforeEach(() => {
  vi.clearAllMocks()
  vi.stubGlobal(
    'ResizeObserver',
    class {
      observe() {}
      disconnect() {}
    },
  )
  vi.stubGlobal('matchMedia', () => ({
    matches: false,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  }))
  vi.stubGlobal(
    'requestAnimationFrame',
    vi.fn(() => 42),
  )
  vi.stubGlobal('cancelAnimationFrame', vi.fn())
})
afterEach(() => vi.unstubAllGlobals())

it('renders, updates theme uniforms in place and releases the WebGL session', async () => {
  const parent = document.createElement('div')
  document.body.appendChild(parent)
  const wrapper = mount(LineWaves, { attachTo: parent })
  await wrapper.vm.$nextTick()
  expect(wrapper.attributes('data-render-state')).toBe('ready')
  expect(wrapper.find('canvas').exists()).toBe(true)
  expect(gpu.render).toHaveBeenCalled()
  await wrapper.setProps({ color1: '#476bf7', lightMode: true })
  expect(gpu.uniforms.uLightMode!.value).toBe(1)
  expect(gpu.uniforms.uColor1!.value).toEqual([71 / 255, 107 / 255, 247 / 255])
  wrapper.unmount()
  expect(cancelAnimationFrame).toHaveBeenCalledWith(42)
  expect(gpu.geometryRemove).toHaveBeenCalledOnce()
  expect(gpu.programRemove).toHaveBeenCalledOnce()
  expect(gpu.lose).toHaveBeenCalledOnce()
  expect(parent.querySelector('canvas')).toBeNull()
  parent.remove()
})

it('renders a static original-shader frame for reduced motion without scheduling animation', () => {
  vi.stubGlobal('matchMedia', () => ({
    matches: true,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  }))
  const wrapper = mount(LineWaves)
  expect(gpu.render).toHaveBeenCalled()
  expect(gpu.uniforms.uTime!.value).toBe(0)
  expect(requestAnimationFrame).not.toHaveBeenCalled()
  wrapper.unmount()
})
