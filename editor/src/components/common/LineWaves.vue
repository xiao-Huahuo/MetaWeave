<!-- Vue port of React Bits Line Waves, Copyright (c) 2026 David Haz, MIT + Commons Clause.
     Original shaders and parameters are preserved; notice: public/licenses/react-bits-line-waves.txt.
     This component owns the renderer, frame, resize observer and interaction listeners. -->
<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Renderer, Program, Mesh, Triangle } from 'ogl'
import { vertexShader, fragmentShader } from './lineWavesShaders'

const props = withDefaults(
  defineProps<{
    /** Animation speed multiplier. */ speed?: number
    /** Inner-region line density. */ innerLineCount?: number
    /** Edge-region line density. */ outerLineCount?: number
    /** Coordinate distortion strength. */ warpIntensity?: number
    /** Wave rotation in degrees. */ rotation?: number
    /** Width of the inner/outer transition. */ edgeFadeWidth?: number
    /** Color cycling speed. */ colorCycleSpeed?: number
    /** Output brightness. */ brightness?: number
    /** First HEX color channel. */ color1?: string
    /** Second HEX color channel. */ color2?: string
    /** Third HEX color channel. */ color3?: string
    /** Enable pointer distortion. */ enableMouseInteraction?: boolean
    /** Pointer distortion strength. */ mouseInfluence?: number
    /** Use the upstream light-background shader. */ lightMode?: boolean
  }>(),
  {
    speed: 0.3,
    innerLineCount: 32,
    outerLineCount: 36,
    warpIntensity: 1,
    rotation: -45,
    edgeFadeWidth: 0,
    colorCycleSpeed: 1,
    brightness: 0.2,
    color1: '#ffffff',
    color2: '#ffffff',
    color3: '#ffffff',
    enableMouseInteraction: true,
    mouseInfluence: 2,
    lightMode: false,
  },
)

const container = ref<HTMLDivElement | null>(null)
const state = ref('initializing')
let renderer: Renderer | undefined
let program: Program | undefined
let geometry: Triangle | undefined
let mesh: Mesh | undefined
let canvas: HTMLCanvasElement | undefined
let observer: ResizeObserver | undefined
let motion: MediaQueryList | undefined
let surface: HTMLElement | null = null
let frame = 0
const currentMouse: [number, number] = [0.5, 0.5]
let targetMouse: [number, number] = [0.5, 0.5]

/** Convert the original six-digit HEX colors into shader RGB values. */
function hexToVec3(hex: string): [number, number, number] {
  const h = hex.replace('#', '')
  return [
    parseInt(h.slice(0, 2), 16) / 255,
    parseInt(h.slice(2, 4), 16) / 255,
    parseInt(h.slice(4, 6), 16) / 255,
  ]
}
/** Update uniforms without rebuilding GPU resources when colors or theme change. */
function syncUniforms() {
  if (!program) return
  const values = {
    uSpeed: props.speed,
    uInnerLines: props.innerLineCount,
    uOuterLines: props.outerLineCount,
    uWarpIntensity: props.warpIntensity,
    uRotation: (props.rotation * Math.PI) / 180,
    uEdgeFadeWidth: props.edgeFadeWidth,
    uColorCycleSpeed: props.colorCycleSpeed,
    uBrightness: props.brightness,
    uColor1: hexToVec3(props.color1),
    uColor2: hexToVec3(props.color2),
    uColor3: hexToVec3(props.color3),
    uMouseInfluence: props.mouseInfluence,
    uEnableMouse: props.enableMouseInteraction,
    uLightMode: props.lightMode ? 1 : 0,
  }
  for (const [key, value] of Object.entries(values)) program.uniforms[key]!.value = value
  if (motion?.matches) render(performance.now())
}
/** Resize from the host box and retain upstream device-pixel coordinates. */
function resize() {
  if (!renderer || !container.value || !program || !canvas) return
  renderer.setSize(container.value.clientWidth, container.value.clientHeight)
  program.uniforms.uResolution!.value = [
    canvas.width,
    canvas.height,
    canvas.width / Math.max(canvas.height, 1),
  ]
  if (motion?.matches) render(performance.now())
}
/** Listen on the containing surface so the decorative canvas cannot intercept input. */
function pointerMove(event: PointerEvent) {
  if (!canvas || !props.enableMouseInteraction || motion?.matches) return
  const rect = canvas.getBoundingClientRect()
  targetMouse = [
    (event.clientX - rect.left) / rect.width,
    1 - (event.clientY - rect.top) / rect.height,
  ]
}
/** Return to the upstream neutral pointer position after leaving the surface. */
function pointerLeave() {
  targetMouse = [0.5, 0.5]
}
/** Render one original frame; schedule only while the page is visible and motion is allowed. */
function render(time: number) {
  frame = 0
  if (!renderer || !program || !mesh || state.value !== 'ready') return
  program.uniforms.uTime!.value = motion?.matches ? 0 : time * 0.001
  for (const axis of [0, 1] as const) {
    currentMouse[axis] += 0.05 * (targetMouse[axis] - currentMouse[axis])
    program.uniforms.uMouse!.value[axis] = props.enableMouseInteraction ? currentMouse[axis] : 0.5
  }
  renderer.render({ scene: mesh })
  if (!document.hidden && !motion?.matches) frame = requestAnimationFrame(render)
}
/** Reduced motion keeps a static frame of the same shader; hidden tabs stop rendering. */
function resume() {
  cancelAnimationFrame(frame)
  frame = 0
  if (!document.hidden) render(performance.now())
}
/** Stop work after context loss rather than repeatedly drawing with invalid resources. */
function contextLost(event: Event) {
  event.preventDefault()
  cancelAnimationFrame(frame)
  frame = 0
  state.value = 'context-lost'
}
/** Release every CPU/GPU resource owned by this instance on unmount. */
function dispose() {
  cancelAnimationFrame(frame)
  observer?.disconnect()
  document.removeEventListener('visibilitychange', resume)
  motion?.removeEventListener('change', resume)
  surface?.removeEventListener('pointermove', pointerMove)
  surface?.removeEventListener('pointerleave', pointerLeave)
  canvas?.removeEventListener('webglcontextlost', contextLost)
  geometry?.remove()
  program?.remove()
  renderer?.gl.getExtension('WEBGL_lose_context')?.loseContext()
  canvas?.remove()
  renderer = undefined
  program = undefined
  mesh = undefined
  geometry = undefined
}
onMounted(() => {
  if (!container.value) return
  try {
    renderer = new Renderer({ alpha: true, premultipliedAlpha: false })
    const gl = renderer.gl
    canvas = gl.canvas as HTMLCanvasElement
    gl.clearColor(0, 0, 0, 0)
    geometry = new Triangle(gl)
    program = new Program(gl, {
      vertex: vertexShader,
      fragment: fragmentShader,
      uniforms: {
        uTime: { value: 0 },
        uResolution: { value: [1, 1, 1] },
        uSpeed: { value: props.speed },
        uInnerLines: { value: props.innerLineCount },
        uOuterLines: { value: props.outerLineCount },
        uWarpIntensity: { value: props.warpIntensity },
        uRotation: { value: (props.rotation * Math.PI) / 180 },
        uEdgeFadeWidth: { value: props.edgeFadeWidth },
        uColorCycleSpeed: { value: props.colorCycleSpeed },
        uBrightness: { value: props.brightness },
        uColor1: { value: hexToVec3(props.color1) },
        uColor2: { value: hexToVec3(props.color2) },
        uColor3: { value: hexToVec3(props.color3) },
        uMouse: { value: new Float32Array([0.5, 0.5]) },
        uMouseInfluence: { value: props.mouseInfluence },
        uEnableMouse: { value: props.enableMouseInteraction },
        uLightMode: { value: props.lightMode ? 1 : 0 },
      },
    })
    mesh = new Mesh(gl, { geometry, program })
    container.value.appendChild(canvas)
    state.value = 'ready'
    motion = window.matchMedia('(prefers-reduced-motion: reduce)')
    observer = new ResizeObserver(resize)
    observer.observe(container.value)
    resize()
    surface = container.value.parentElement
    surface?.addEventListener('pointermove', pointerMove)
    surface?.addEventListener('pointerleave', pointerLeave)
    document.addEventListener('visibilitychange', resume)
    motion.addEventListener('change', resume)
    canvas.addEventListener('webglcontextlost', contextLost)
    resume()
  } catch {
    state.value = 'unavailable'
    dispose()
  }
})
watch(() => ({ ...props }), syncUniforms)
onBeforeUnmount(dispose)
</script>
<template>
  <div ref="container" class="line-waves" :data-render-state="state" aria-hidden="true" />
</template>
<style scoped>
.line-waves {
  width: 100%;
  height: 100%;
  overflow: hidden;
  pointer-events: none;
}
.line-waves :deep(canvas) {
  display: block;
  width: 100%;
  height: 100%;
}
</style>
