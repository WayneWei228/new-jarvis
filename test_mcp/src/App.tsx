﻿import { useState, useEffect, useRef, useCallback } from 'react'

interface LightSpot {
  id: number
  x: number
  y: number
  width: number
  height: number
  rotation: number
  speedX: number
  speedY: number
  imageSrc: string
  deformedSrc: string
  name: string
  squeezeAmount: number
  targetDeform: number
  stickTimer: number
  savedSpeedX: number
  savedSpeedY: number
  phase: 'moving' | 'sticking' | 'leaving'
  stuckSide: 'left' | 'right' | 'top' | 'bottom' | null
  stuckFrameIdx: number
  stickCooldown: number
  maxStickDuration: number
  leaveDuration: number
  wanderPhaseX: number
  wanderPhaseY: number
  wanderFreqX: number
  wanderFreqY: number
  breathPhase: number
  breathSpeed: number
  hue: number
  saturation: number
  lightness: number
  eyeTargetX: number
  eyeTargetY: number
  eyeTargetScale: number
  eyeAngle: number
}

interface Frame {
  id: string
  x: number
  y: number
  width: number
  height: number
  label: string
  color: string
}

const SPOT_IMAGES = {
  img8: "/assets/spots/img8.svg",
  img9: "/assets/spots/img9.svg",
  img7: "/assets/spots/img7.svg",
  img10: "/assets/spots/img10.svg",
  img6: "/assets/spots/img6.svg",
  img5: "/assets/spots/img5.svg",
  img11: "/assets/spots/img11.svg",
  img12: "/assets/spots/img12.svg",
  img2: "/assets/spots/img2.svg",
  img1: "/assets/spots/img1.svg",
  img3: "/assets/spots/img3.svg",
  img4: "/assets/spots/img4.svg",
  img13: "/assets/spots/img13.svg",
  img14: "/assets/spots/img14.svg",
  img15: "/assets/spots/img15.svg",
  img16: "/assets/spots/img16.svg",
  img17: "/assets/spots/img17.svg",
  img18: "/assets/spots/img18.svg",
  img16d: "/assets/spots/img16d.svg",
  img17d: "/assets/spots/img17d.svg",
  img18d: "/assets/spots/img18d.svg",
  img1d: "/assets/spots/img1d.svg",
}

const SPOT_COLORS: {hue: number; saturation: number; lightness: number}[] = [
  { hue: 140, saturation: 70, lightness: 55 },
  { hue: 155, saturation: 65, lightness: 50 },
  { hue: 130, saturation: 60, lightness: 60 },
  { hue: 165, saturation: 55, lightness: 52 },
  { hue: 120, saturation: 50, lightness: 58 },
  { hue: 150, saturation: 72, lightness: 48 },
  { hue: 145, saturation: 68, lightness: 53 },
  { hue: 160, saturation: 58, lightness: 56 },
  { hue: 135, saturation: 62, lightness: 50 },
  { hue: 170, saturation: 55, lightness: 54 },
  { hue: 125, saturation: 66, lightness: 57 },
  { hue: 142, saturation: 64, lightness: 51 },
]

function makeSpot(base: Omit<LightSpot, 'breathPhase' | 'breathSpeed' | 'hue' | 'saturation' | 'lightness' | 'eyeTargetX' | 'eyeTargetY' | 'eyeTargetScale' | 'eyeAngle' | 'stickCooldown' | 'maxStickDuration' | 'leaveDuration'>): LightSpot {
  const c = SPOT_COLORS[base.id % SPOT_COLORS.length]
  return {
    ...base,
    breathPhase: Math.random() * Math.PI * 2,
    breathSpeed: 0.02 + Math.random() * 0.01,
    hue: c.hue + (Math.random() - 0.5) * 10,
    saturation: c.saturation + (Math.random() - 0.5) * 8,
    lightness: c.lightness + (Math.random() - 0.5) * 6,
    eyeTargetX: 0,
    eyeTargetY: 0,
    eyeTargetScale: 1,
    eyeAngle: 0,
    stickCooldown: Math.floor(Math.random() * 300),
    maxStickDuration: 120 + Math.floor(Math.random() * 360),
    leaveDuration: 100 + Math.floor(Math.random() * 200),
  }
}

const INITIAL_SPOTS: LightSpot[] = [
  makeSpot({ id: 1, x: 86, y: 523, width: 121, height: 126, rotation: 14.92, speedX: 0.6, speedY: -0.4, imageSrc: SPOT_IMAGES.img8, deformedSrc: SPOT_IMAGES.img16d, name: '光斑8', squeezeAmount: 0, targetDeform: 0, stickTimer: 0, savedSpeedX: 0, savedSpeedY: 0, phase: 'moving', stuckSide: null, stuckFrameIdx: -1, wanderPhaseX: 0, wanderPhaseY: 2.1, wanderFreqX: 0.008, wanderFreqY: 0.011 }),
  makeSpot({ id: 2, x: 819, y: 353, width: 81, height: 85, rotation: 14.92, speedX: -0.5, speedY: 0.7, imageSrc: SPOT_IMAGES.img9, deformedSrc: SPOT_IMAGES.img16d, name: '光斑8', squeezeAmount: 0, targetDeform: 0, stickTimer: 0, savedSpeedX: 0, savedSpeedY: 0, phase: 'moving', stuckSide: null, stuckFrameIdx: -1, wanderPhaseX: 1.3, wanderPhaseY: 4.7, wanderFreqX: 0.012, wanderFreqY: 0.009 }),
  makeSpot({ id: 3, x: 179, y: 419, width: 98, height: 97, rotation: -37.56, speedX: 0.7, speedY: -0.3, imageSrc: SPOT_IMAGES.img7, deformedSrc: SPOT_IMAGES.img17d, name: '光斑7', squeezeAmount: 0, targetDeform: 0, stickTimer: 0, savedSpeedX: 0, savedSpeedY: 0, phase: 'moving', stuckSide: null, stuckFrameIdx: -1, wanderPhaseX: 3.8, wanderPhaseY: 0.5, wanderFreqX: 0.007, wanderFreqY: 0.013 }),
  makeSpot({ id: 4, x: 22, y: 367, width: 72, height: 72, rotation: -37.56, speedX: -0.4, speedY: 0.6, imageSrc: SPOT_IMAGES.img10, deformedSrc: SPOT_IMAGES.img17d, name: '光斑7', squeezeAmount: 0, targetDeform: 0, stickTimer: 0, savedSpeedX: 0, savedSpeedY: 0, phase: 'moving', stuckSide: null, stuckFrameIdx: -1, wanderPhaseX: 5.2, wanderPhaseY: 1.8, wanderFreqX: 0.015, wanderFreqY: 0.01 }),
  makeSpot({ id: 5, x: 327, y: 477, width: 98, height: 95, rotation: -145.88, speedX: 0.5, speedY: -0.6, imageSrc: SPOT_IMAGES.img6, deformedSrc: SPOT_IMAGES.img18d, name: '光斑6', squeezeAmount: 0, targetDeform: 0, stickTimer: 0, savedSpeedX: 0, savedSpeedY: 0, phase: 'moving', stuckSide: null, stuckFrameIdx: -1, wanderPhaseX: 0.7, wanderPhaseY: 3.3, wanderFreqX: 0.009, wanderFreqY: 0.014 }),
  makeSpot({ id: 6, x: 446, y: 671, width: 68, height: 65, rotation: 162.84, speedX: -0.8, speedY: 0.4, imageSrc: SPOT_IMAGES.img5, deformedSrc: SPOT_IMAGES.img18d, name: '光斑5', squeezeAmount: 0, targetDeform: 0, stickTimer: 0, savedSpeedX: 0, savedSpeedY: 0, phase: 'moving', stuckSide: null, stuckFrameIdx: -1, wanderPhaseX: 2.9, wanderPhaseY: 5.6, wanderFreqX: 0.011, wanderFreqY: 0.007 }),
  makeSpot({ id: 7, x: 958, y: 638, width: 90, height: 86, rotation: 162.84, speedX: 0.6, speedY: -0.5, imageSrc: SPOT_IMAGES.img11, deformedSrc: SPOT_IMAGES.img18d, name: '光斑5', squeezeAmount: 0, targetDeform: 0, stickTimer: 0, savedSpeedX: 0, savedSpeedY: 0, phase: 'moving', stuckSide: null, stuckFrameIdx: -1, wanderPhaseX: 4.1, wanderPhaseY: 0.9, wanderFreqX: 0.013, wanderFreqY: 0.008 }),
  makeSpot({ id: 8, x: 968, y: 842, width: 59, height: 58, rotation: 146.41, speedX: -0.7, speedY: 0.3, imageSrc: SPOT_IMAGES.img12, deformedSrc: SPOT_IMAGES.img17d, name: '光斑5', squeezeAmount: 0, targetDeform: 0, stickTimer: 0, savedSpeedX: 0, savedSpeedY: 0, phase: 'moving', stuckSide: null, stuckFrameIdx: -1, wanderPhaseX: 1.6, wanderPhaseY: 3.9, wanderFreqX: 0.01, wanderFreqY: 0.012 }),
  makeSpot({ id: 9, x: 113, y: 420, width: 99, height: 98, rotation: 136.25, speedX: 0.4, speedY: -0.7, imageSrc: SPOT_IMAGES.img2, deformedSrc: SPOT_IMAGES.img16d, name: '光斑2', squeezeAmount: 0, targetDeform: 0, stickTimer: 0, savedSpeedX: 0, savedSpeedY: 0, phase: 'moving', stuckSide: null, stuckFrameIdx: -1, wanderPhaseX: 5.8, wanderPhaseY: 2.4, wanderFreqX: 0.006, wanderFreqY: 0.015 }),
  makeSpot({ id: 10, x: 388, y: 447, width: 72, height: 70, rotation: 151.71, speedX: -0.6, speedY: 0.5, imageSrc: SPOT_IMAGES.img1, deformedSrc: SPOT_IMAGES.img1d, name: '光斑1', squeezeAmount: 0, targetDeform: 0, stickTimer: 0, savedSpeedX: 0, savedSpeedY: 0, phase: 'moving', stuckSide: null, stuckFrameIdx: -1, wanderPhaseX: 3.2, wanderPhaseY: 5.1, wanderFreqX: 0.014, wanderFreqY: 0.009 }),
  makeSpot({ id: 11, x: 491, y: 409, width: 95, height: 93, rotation: 151.71, speedX: 0.8, speedY: -0.4, imageSrc: SPOT_IMAGES.img1, deformedSrc: SPOT_IMAGES.img1d, name: '光斑1', squeezeAmount: 0, targetDeform: 0, stickTimer: 0, savedSpeedX: 0, savedSpeedY: 0, phase: 'moving', stuckSide: null, stuckFrameIdx: -1, wanderPhaseX: 0.4, wanderPhaseY: 1.2, wanderFreqX: 0.008, wanderFreqY: 0.011 }),
  makeSpot({ id: 12, x: 472, y: 813, width: 63, height: 65, rotation: 130.88, speedX: -0.5, speedY: 0.6, imageSrc: SPOT_IMAGES.img3, deformedSrc: SPOT_IMAGES.img18d, name: '光斑1', squeezeAmount: 0, targetDeform: 0, stickTimer: 0, savedSpeedX: 0, savedSpeedY: 0, phase: 'moving', stuckSide: null, stuckFrameIdx: -1, wanderPhaseX: 2.5, wanderPhaseY: 4.3, wanderFreqX: 0.012, wanderFreqY: 0.007 }),
  makeSpot({ id: 13, x: 494, y: 490, width: 94, height: 91, rotation: 154.7, speedX: 0.7, speedY: -0.5, imageSrc: SPOT_IMAGES.img4, deformedSrc: SPOT_IMAGES.img16d, name: '光斑3', squeezeAmount: 0, targetDeform: 0, stickTimer: 0, savedSpeedX: 0, savedSpeedY: 0, phase: 'moving', stuckSide: null, stuckFrameIdx: -1, wanderPhaseX: 4.9, wanderPhaseY: 0.3, wanderFreqX: 0.007, wanderFreqY: 0.013 }),
  makeSpot({ id: 14, x: 957, y: 762, width: 45, height: 48, rotation: 106, speedX: -0.9, speedY: 0.3, imageSrc: SPOT_IMAGES.img13, deformedSrc: SPOT_IMAGES.img17d, name: '光斑3', squeezeAmount: 0, targetDeform: 0, stickTimer: 0, savedSpeedX: 0, savedSpeedY: 0, phase: 'moving', stuckSide: null, stuckFrameIdx: -1, wanderPhaseX: 1.1, wanderPhaseY: 3.6, wanderFreqX: 0.015, wanderFreqY: 0.01 }),
  makeSpot({ id: 15, x: 934, y: 469, width: 92, height: 87, rotation: 158.53, speedX: 0.5, speedY: -0.8, imageSrc: SPOT_IMAGES.img14, deformedSrc: SPOT_IMAGES.img16d, name: '光斑3', squeezeAmount: 0, targetDeform: 0, stickTimer: 0, savedSpeedX: 0, savedSpeedY: 0, phase: 'moving', stuckSide: null, stuckFrameIdx: -1, wanderPhaseX: 3.5, wanderPhaseY: 5.9, wanderFreqX: 0.009, wanderFreqY: 0.014 }),
  makeSpot({ id: 16, x: 846, y: 546, width: 68, height: 65, rotation: 158.53, speedX: -0.6, speedY: 0.4, imageSrc: SPOT_IMAGES.img15, deformedSrc: SPOT_IMAGES.img16d, name: '光斑3', squeezeAmount: 0, targetDeform: 0, stickTimer: 0, savedSpeedX: 0, savedSpeedY: 0, phase: 'moving', stuckSide: null, stuckFrameIdx: -1, wanderPhaseX: 5.4, wanderPhaseY: 2.7, wanderFreqX: 0.011, wanderFreqY: 0.008 }),
  makeSpot({ id: 17, x: 805, y: 499, width: 92, height: 87, rotation: 158.53, speedX: 0.4, speedY: -0.6, imageSrc: SPOT_IMAGES.img14, deformedSrc: SPOT_IMAGES.img16d, name: '光斑3', squeezeAmount: 0, targetDeform: 0, stickTimer: 0, savedSpeedX: 0, savedSpeedY: 0, phase: 'moving', stuckSide: null, stuckFrameIdx: -1, wanderPhaseX: 0.9, wanderPhaseY: 4.5, wanderFreqX: 0.013, wanderFreqY: 0.006 }),
  makeSpot({ id: 18, x: 1055, y: 510, width: 72, height: 68, rotation: 158.53, speedX: -0.7, speedY: 0.5, imageSrc: SPOT_IMAGES.img15, deformedSrc: SPOT_IMAGES.img16d, name: '光斑3', squeezeAmount: 0, targetDeform: 0, stickTimer: 0, savedSpeedX: 0, savedSpeedY: 0, phase: 'moving', stuckSide: null, stuckFrameIdx: -1, wanderPhaseX: 2.3, wanderPhaseY: 1.5, wanderFreqX: 0.01, wanderFreqY: 0.012 }),
  makeSpot({ id: 19, x: 1154, y: 561, width: 92, height: 87, rotation: 158.53, speedX: 0.6, speedY: -0.3, imageSrc: SPOT_IMAGES.img15, deformedSrc: SPOT_IMAGES.img16d, name: '光斑3', squeezeAmount: 0, targetDeform: 0, stickTimer: 0, savedSpeedX: 0, savedSpeedY: 0, phase: 'moving', stuckSide: null, stuckFrameIdx: -1, wanderPhaseX: 4.6, wanderPhaseY: 3.1, wanderFreqX: 0.008, wanderFreqY: 0.015 }),
  makeSpot({ id: 20, x: 1279, y: 533, width: 36, height: 34, rotation: 158.53, speedX: -0.8, speedY: 0.7, imageSrc: SPOT_IMAGES.img16, deformedSrc: SPOT_IMAGES.img17d, name: '光斑3', squeezeAmount: 0, targetDeform: 0, stickTimer: 0, savedSpeedX: 0, savedSpeedY: 0, phase: 'moving', stuckSide: null, stuckFrameIdx: -1, wanderPhaseX: 1.8, wanderPhaseY: 5.3, wanderFreqX: 0.014, wanderFreqY: 0.009 }),
  makeSpot({ id: 21, x: 748, y: 465, width: 86, height: 81, rotation: 158.53, speedX: 0.5, speedY: -0.4, imageSrc: SPOT_IMAGES.img17, deformedSrc: SPOT_IMAGES.img16d, name: '光斑3', squeezeAmount: 0, targetDeform: 0, stickTimer: 0, savedSpeedX: 0, savedSpeedY: 0, phase: 'moving', stuckSide: null, stuckFrameIdx: -1, wanderPhaseX: 3.9, wanderPhaseY: 0.7, wanderFreqX: 0.007, wanderFreqY: 0.013 }),
  makeSpot({ id: 22, x: 1165, y: 457, width: 32, height: 30, rotation: 165, speedX: -0.6, speedY: 0.8, imageSrc: SPOT_IMAGES.img18, deformedSrc: SPOT_IMAGES.img18d, name: '光斑3', squeezeAmount: 0, targetDeform: 0, stickTimer: 0, savedSpeedX: 0, savedSpeedY: 0, phase: 'moving', stuckSide: null, stuckFrameIdx: -1, wanderPhaseX: 5.1, wanderPhaseY: 2.9, wanderFreqX: 0.012, wanderFreqY: 0.008 }),
  makeSpot({ id: 23, x: 607, y: 393, width: 99, height: 98, rotation: 136.25, speedX: 0.7, speedY: -0.5, imageSrc: SPOT_IMAGES.img2, deformedSrc: SPOT_IMAGES.img16d, name: '光斑4', squeezeAmount: 0, targetDeform: 0, stickTimer: 0, savedSpeedX: 0, savedSpeedY: 0, phase: 'moving', stuckSide: null, stuckFrameIdx: -1, wanderPhaseX: 0.2, wanderPhaseY: 4.8, wanderFreqX: 0.009, wanderFreqY: 0.011 }),
  makeSpot({ id: 24, x: 566, y: 500, width: 77, height: 76, rotation: 136.25, speedX: -0.4, speedY: 0.6, imageSrc: SPOT_IMAGES.img2, deformedSrc: SPOT_IMAGES.img16d, name: '光斑4', squeezeAmount: 0, targetDeform: 0, stickTimer: 0, savedSpeedX: 0, savedSpeedY: 0, phase: 'moving', stuckSide: null, stuckFrameIdx: -1, wanderPhaseX: 2.7, wanderPhaseY: 1.4, wanderFreqX: 0.013, wanderFreqY: 0.007 }),
  makeSpot({ id: 25, x: 700, y: 565, width: 99, height: 98, rotation: 136.25, speedX: 0.3, speedY: -0.7, imageSrc: SPOT_IMAGES.img2, deformedSrc: SPOT_IMAGES.img16d, name: '光斑4', squeezeAmount: 0, targetDeform: 0, stickTimer: 0, savedSpeedX: 0, savedSpeedY: 0, phase: 'moving', stuckSide: null, stuckFrameIdx: -1, wanderPhaseX: 4.3, wanderPhaseY: 3.7, wanderFreqX: 0.01, wanderFreqY: 0.014 }),
  makeSpot({ id: 26, x: 1034, y: 779, width: 45, height: 48, rotation: 106, speedX: -0.5, speedY: 0.4, imageSrc: SPOT_IMAGES.img13, deformedSrc: SPOT_IMAGES.img17d, name: '光斑3', squeezeAmount: 0, targetDeform: 0, stickTimer: 0, savedSpeedX: 0, savedSpeedY: 0, phase: 'moving', stuckSide: null, stuckFrameIdx: -1, wanderPhaseX: 1.5, wanderPhaseY: 5.5, wanderFreqX: 0.015, wanderFreqY: 0.01 }),
  makeSpot({ id: 27, x: 587, y: 855, width: 63, height: 65, rotation: 130.88, speedX: 0.6, speedY: -0.3, imageSrc: SPOT_IMAGES.img3, deformedSrc: SPOT_IMAGES.img18d, name: '光斑1', squeezeAmount: 0, targetDeform: 0, stickTimer: 0, savedSpeedX: 0, savedSpeedY: 0, phase: 'moving', stuckSide: null, stuckFrameIdx: -1, wanderPhaseX: 3.4, wanderPhaseY: 0.1, wanderFreqX: 0.008, wanderFreqY: 0.012 }),
  ...Array.from({length: 25}, (_, i) => {
    const id = 28 + i
    const imgKeys = [SPOT_IMAGES.img1, SPOT_IMAGES.img2, SPOT_IMAGES.img3, SPOT_IMAGES.img4, SPOT_IMAGES.img5, SPOT_IMAGES.img6, SPOT_IMAGES.img7, SPOT_IMAGES.img8, SPOT_IMAGES.img9, SPOT_IMAGES.img10, SPOT_IMAGES.img11, SPOT_IMAGES.img12, SPOT_IMAGES.img13, SPOT_IMAGES.img14, SPOT_IMAGES.img15, SPOT_IMAGES.img16, SPOT_IMAGES.img17, SPOT_IMAGES.img18]
    const defKeys = [SPOT_IMAGES.img1d, SPOT_IMAGES.img16d, SPOT_IMAGES.img17d, SPOT_IMAGES.img18d]
    const sz = 25 + Math.random() * 80
    return makeSpot({
      id, x: Math.random() * 1300 + 50, y: Math.random() * 900 + 50,
      width: sz, height: sz * (0.9 + Math.random() * 0.2),
      rotation: Math.random() * 360,
      speedX: (Math.random() - 0.5) * 1.6,
      speedY: (Math.random() - 0.5) * 1.6,
      imageSrc: imgKeys[id % imgKeys.length],
      deformedSrc: defKeys[id % defKeys.length],
      name: `光斑${id}`, squeezeAmount: 0, targetDeform: 0, stickTimer: 0,
      savedSpeedX: 0, savedSpeedY: 0, phase: 'moving', stuckSide: null, stuckFrameIdx: -1,
      wanderPhaseX: Math.random() * 6, wanderPhaseY: Math.random() * 6,
      wanderFreqX: 0.006 + Math.random() * 0.01, wanderFreqY: 0.006 + Math.random() * 0.01,
    })
  }),
]

const FRAMES: Frame[] = [
  { id: 'text', x: 31, y: 32, width: 1380, height: 312, label: 'TEXT', color: '#b9b9b9' },
  { id: 'video1', x: 50, y: 696, width: 352, height: 331, label: 'VIDEO 1 - DITHERING STUDIO', color: '#22c55e' },
  { id: 'video2', x: 544, y: 696, width: 352, height: 331, label: 'VIDEO 2 - DITHERING STUDIO', color: '#16a34a' },
  { id: 'sound', x: 1038, y: 696, width: 352, height: 331, label: 'SOUND', color: '#10b981' },
]

const COLLISION_FRAMES: Frame[] = FRAMES.map(f => {
  if (f.id === 'text') return f
  const inset = 10
  const scale = 0.9
  const innerW = f.width - inset * 2
  const innerH = f.height - inset * 2
  const cw = innerW * scale
  const ch = innerH * scale
  const cx = f.x + inset + (innerW - cw) / 2
  const cy = f.y + inset + (innerH - ch) / 2
  return { ...f, x: cx, y: cy, width: cw, height: ch }
})

const SQUEEZE_ZONE = 150

function findClosestFrameEdge(cx: number, cy: number, hw: number, hh: number, frames: Frame[]): { side: 'left' | 'right' | 'top' | 'bottom' | null; dist: number; frameIdx: number; hitFrame: boolean; bounceDir: { x: number; y: number } } {
  let bestSide: 'left' | 'right' | 'top' | 'bottom' | null = null
  let bestDist = Infinity
  let bestFrameIdx = -1
  let hitFrame = false
  let bx = 0, by = 0

  const sl = cx - hw
  const sr = cx + hw
  const st = cy - hh
  const sb = cy + hh

  for (let fi = 0; fi < frames.length; fi++) {
    const f = frames[fi]
    const fl = f.x
    const fr = f.x + f.width
    const ft = f.y
    const fb = f.y + f.height

    const overlapX = Math.min(sr, fr) - Math.max(sl, fl)
    const overlapY = Math.min(sb, fb) - Math.max(st, ft)

    if (overlapX > 0 && overlapY > 0) {
      hitFrame = true
      bestFrameIdx = fi
      bestDist = 0

      const pushL = sr - fl
      const pushR = fr - sl
      const pushT = sb - ft
      const pushB = fb - st
      const minPush = Math.min(pushL, pushR, pushT, pushB)

      if (minPush === pushL) { bestSide = 'right'; bx = -1; by = 0 }
      else if (minPush === pushR) { bestSide = 'left'; bx = 1; by = 0 }
      else if (minPush === pushT) { bestSide = 'bottom'; bx = 0; by = -1 }
      else { bestSide = 'top'; bx = 0; by = 1 }
      break
    }

    const nearX = Math.max(fl, Math.min(fr, cx))
    const nearY = Math.max(ft, Math.min(fb, cy))

    let dist: number
    if (cy >= ft && cy <= fb) {
      dist = cx < fl ? fl - sr : sl - fr
      dist = Math.max(0, dist)
    } else if (cx >= fl && cx <= fr) {
      dist = cy < ft ? ft - sb : st - fb
      dist = Math.max(0, dist)
    } else {
      const dx = cx < fl ? fl - sr : sl - fr
      const dy = cy < ft ? ft - sb : st - fb
      dist = Math.sqrt(Math.max(0, dx) ** 2 + Math.max(0, dy) ** 2)
    }

    if (dist < bestDist) {
      bestDist = dist
      bestFrameIdx = fi

      if (cy >= ft && cy <= fb) {
        if (cx < fl) { bestSide = 'right'; bx = -1; by = 0 }
        else { bestSide = 'left'; bx = 1; by = 0 }
      } else if (cx >= fl && cx <= fr) {
        if (cy < ft) { bestSide = 'bottom'; bx = 0; by = -1 }
        else { bestSide = 'top'; bx = 0; by = 1 }
      } else {
        const ddx = nearX - cx
        const ddy = nearY - cy
        if (Math.abs(ddx) > Math.abs(ddy)) {
          if (ddx > 0) { bestSide = 'right'; bx = -1; by = 0 }
          else { bestSide = 'left'; bx = 1; by = 0 }
        } else {
          if (ddy > 0) { bestSide = 'bottom'; bx = 0; by = -1 }
          else { bestSide = 'top'; bx = 0; by = 1 }
        }
      }
    }
  }

  return { side: bestSide, dist: bestDist, frameIdx: bestFrameIdx, hitFrame, bounceDir: { x: bx, y: by } }
}

function smootherStep(t: number) {
  return t * t * t * (t * (t * 6 - 15) + 10)
}

function smoothStep(t: number) {
  return t * t * (3 - 2 * t)
}

function catmullRomToBezier(p0: {x: number; y: number}, p1: {x: number; y: number}, p2: {x: number; y: number}, p3: {x: number; y: number}, tension = 0.35) {
  return {
    cp1x: p1.x + (p2.x - p0.x) * tension,
    cp1y: p1.y + (p2.y - p0.y) * tension,
    cp2x: p2.x - (p3.x - p1.x) * tension,
    cp2y: p2.y - (p3.y - p1.y) * tension,
  }
}

function getDeformPoints(cx: number, cy: number, r: number, deform: number, side: 'left' | 'right' | 'top' | 'bottom' | null, numPoints: number) {
  const points: {x: number; y: number}[] = []
  const activeSide = side || 'top'
  const d = Math.min(deform, 1.0)

  const concaveDepth = d * 0.7
  const concaveWidth = 0.8

  for (let i = 0; i < numPoints; i++) {
    const angle = (i / numPoints) * Math.PI * 2
    const cosA = Math.cos(angle)
    const sinA = Math.sin(angle)

    let px = cx + cosA * r
    let py = cy + sinA * r

    let toward: number
    let perpendicular: number
    if (activeSide === 'top') {
      toward = -sinA
      perpendicular = Math.abs(cosA)
    } else if (activeSide === 'bottom') {
      toward = sinA
      perpendicular = Math.abs(cosA)
    } else if (activeSide === 'left') {
      toward = -cosA
      perpendicular = Math.abs(sinA)
    } else {
      toward = cosA
      perpendicular = Math.abs(sinA)
    }

    if (toward > 0) {
      const facingAmount = toward * toward
      const spreadFalloff = 1 - Math.pow(perpendicular / 1, 2) * (1 - concaveWidth)
      const inward = facingAmount * spreadFalloff * concaveDepth * r

      if (activeSide === 'top') py += inward
      else if (activeSide === 'bottom') py -= inward
      else if (activeSide === 'left') px += inward
      else px -= inward

      const edgePull = toward * (1 - toward) * 4
      const pullAmount = edgePull * d * r * 0.14
      if (activeSide === 'top') py += pullAmount
      else if (activeSide === 'bottom') py -= pullAmount
      else if (activeSide === 'left') px += pullAmount
      else px -= pullAmount
    }

    points.push({ x: px, y: py })
  }
  return points
}

function drawSmoothShape(ctx: CanvasRenderingContext2D, points: {x: number; y: number}[]) {
  const len = points.length
  ctx.beginPath()
  ctx.moveTo(points[0].x, points[0].y)
  for (let i = 0; i < len; i++) {
    const p0 = points[(i - 1 + len) % len]
    const p1 = points[i]
    const p2 = points[(i + 1) % len]
    const p3 = points[(i + 2) % len]
    const cp = catmullRomToBezier(p0, p1, p2, p3)
    ctx.bezierCurveTo(cp.cp1x, cp.cp1y, cp.cp2x, cp.cp2y, p2.x, p2.y)
  }
  ctx.closePath()
}

const EYE_CENTER_X = 720
const EYE_CENTER_Y = 522

function computeEyeTargets(spots: LightSpot[]): number {
  const total = spots.length
  const pupilCount = Math.floor(total * 0.12)
  const innerRingCount = Math.floor(total * 0.22)
  const outerRingCount = Math.floor(total * 0.25)
  const wingCount = total - pupilCount - innerRingCount - outerRingCount

  let idx = 0

  for (let i = 0; i < pupilCount; i++, idx++) {
    const s = spots[idx]
    const a = (i / pupilCount) * Math.PI * 2 + Math.random() * 0.3
    const dist = Math.random() * 28
    s.eyeTargetX = EYE_CENTER_X + Math.cos(a) * dist - s.width / 2
    s.eyeTargetY = EYE_CENTER_Y + Math.sin(a) * dist - s.height / 2
    s.eyeTargetScale = 0.3 + Math.random() * 0.15
    s.eyeAngle = a
  }

  for (let i = 0; i < innerRingCount; i++, idx++) {
    const s = spots[idx]
    const a = (i / innerRingCount) * Math.PI * 2 + Math.random() * 0.15
    const baseR = 110 + Math.random() * 20
    s.eyeTargetX = EYE_CENTER_X + Math.cos(a) * baseR - s.width / 2
    s.eyeTargetY = EYE_CENTER_Y + Math.sin(a) * baseR - s.height / 2
    s.eyeTargetScale = 0.7 + Math.random() * 0.3
    s.eyeAngle = a
  }

  for (let i = 0; i < outerRingCount; i++, idx++) {
    const s = spots[idx]
    const a = (i / outerRingCount) * Math.PI * 2 + Math.random() * 0.1
    const baseR = 160 + Math.random() * 25
    s.eyeTargetX = EYE_CENTER_X + Math.cos(a) * baseR - s.width / 2
    s.eyeTargetY = EYE_CENTER_Y + Math.sin(a) * baseR - s.height / 2
    s.eyeTargetScale = 0.8 + Math.random() * 0.2
    s.eyeAngle = a
  }

  const leftWing = Math.floor(wingCount / 2)
  const rightWing = wingCount - leftWing

  for (let i = 0; i < leftWing; i++, idx++) {
    const s = spots[idx]
    const t = (i + 1) / (leftWing + 1)
    const spread = t * 350 + Math.random() * 30
    const yOff = Math.sin(t * Math.PI) * (40 + Math.random() * 25)
    const side = i % 2 === 0 ? -1 : 1
    s.eyeTargetX = EYE_CENTER_X - 180 - spread - s.width / 2
    s.eyeTargetY = EYE_CENTER_Y + side * yOff * (1 - t * 0.5) - s.height / 2
    s.eyeTargetScale = 0.4 + t * 0.4
    s.eyeAngle = Math.PI + t * 0.3 * side
  }

  for (let i = 0; i < rightWing; i++, idx++) {
    const s = spots[idx]
    const t = (i + 1) / (rightWing + 1)
    const spread = t * 350 + Math.random() * 30
    const yOff = Math.sin(t * Math.PI) * (40 + Math.random() * 25)
    const side = i % 2 === 0 ? -1 : 1
    s.eyeTargetX = EYE_CENTER_X + 180 + spread - s.width / 2
    s.eyeTargetY = EYE_CENTER_Y + side * yOff * (1 - t * 0.5) - s.height / 2
    s.eyeTargetScale = 0.4 + t * 0.4
    s.eyeAngle = t * 0.3 * side
  }

  return pupilCount
}

const LightSpotsComponent = () => {
  const spotsRef = useRef<LightSpot[]>(INITIAL_SPOTS.map(s => ({ ...s })))
  const animationRef = useRef<number>(0)
  const lastTimeRef = useRef(0)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const imagesRef = useRef<Map<string, HTMLImageElement>>(new Map())
  const imagesLoadedRef = useRef(false)
  const gatheringRef = useRef(false)
  const gatherProgressRef = useRef(0)
  const eyeTargetsComputedRef = useRef(false)
  const pupilCountRef = useRef(0)

  useEffect(() => {
    const allSrcs = new Set<string>()
    INITIAL_SPOTS.forEach(s => { allSrcs.add(s.imageSrc); allSrcs.add(s.deformedSrc) })
    let loaded = 0
    const total = allSrcs.size
    allSrcs.forEach(src => {
      const img = new Image()
      img.crossOrigin = 'anonymous'
      img.onload = () => {
        imagesRef.current.set(src, img)
        loaded++
        if (loaded >= total) imagesLoadedRef.current = true
      }
      img.onerror = () => {
        loaded++
        if (loaded >= total) imagesLoadedRef.current = true
      }
      img.src = src
    })
  }, [])

  const animate = useCallback((time: number) => {
    const delta = lastTimeRef.current ? (time - lastTimeRef.current) / 16 : 1
    lastTimeRef.current = time

    const vw = 1440
    const vh = 1024
    const spots = spotsRef.current

    for (let i = 0; i < spots.length; i++) {
      const s = spots[i]
      const cx = s.x + s.width / 2
      const cy = s.y + s.height / 2
      const r = Math.max(s.width, s.height) * 0.5

      s.breathPhase = (s.breathPhase || 0) + (s.breathSpeed || 0.02) * delta

      if (gatheringRef.current) {
        if (!eyeTargetsComputedRef.current) {
          const pc = computeEyeTargets(spots)
          pupilCountRef.current = pc
          eyeTargetsComputedRef.current = true
          for (const sp of spots) {
            sp.savedSpeedX = sp.speedX
            sp.savedSpeedY = sp.speedY
          }
        }

        gatherProgressRef.current = Math.min(gatherProgressRef.current + 0.015 * delta, 1)
        const gp = gatherProgressRef.current
        const ease = gp * gp * (3 - 2 * gp)

        const pupilSwayX = Math.sin(time * 0.0008) * 55 + Math.sin(time * 0.0013 + 1.2) * 25
        const pupilSwayY = Math.cos(time * 0.0006) * 12 + Math.sin(time * 0.001 + 2.5) * 8
        const isPupil = i < pupilCountRef.current

        const tx = s.eyeTargetX + (isPupil ? pupilSwayX * ease : 0)
        const ty = s.eyeTargetY + (isPupil ? pupilSwayY * ease : 0)
        const dx = tx - s.x
        const dy = ty - s.y
        const lerpSpeed = 0.04 + ease * 0.06
        s.x += dx * lerpSpeed * delta
        s.y += dy * lerpSpeed * delta

        const spotR = Math.max(s.width, s.height) * 0.5 * (s.eyeTargetScale || 1)
        const topLimit = 355 + spotR
        const bottomLimit = 686 - spotR
        if (s.y + s.height / 2 < topLimit) s.y = topLimit - s.height / 2
        if (s.y + s.height / 2 > bottomLimit) s.y = bottomLimit - s.height / 2

        const wobble = Math.sin(s.breathPhase * 2 + i * 0.7) * (3 - ease * 2.5)
        s.x += wobble * 0.3 * delta
        s.y += Math.cos(s.breathPhase * 1.5 + i) * wobble * 0.2 * delta

        s.squeezeAmount *= 0.9
        if (s.squeezeAmount < 0.005) { s.squeezeAmount = 0; s.stuckSide = null }
        s.phase = 'moving'
        s.speedX = 0
        s.speedY = 0

      } else {
        if (eyeTargetsComputedRef.current) {
          gatherProgressRef.current = Math.max(gatherProgressRef.current - 0.02 * delta, 0)
          if (gatherProgressRef.current > 0.01) {
            const gp = gatherProgressRef.current
            const restoreForce = 1 - gp
            s.speedX += (s.savedSpeedX - s.speedX) * 0.03 * restoreForce * delta
            s.speedY += (s.savedSpeedY - s.speedY) * 0.03 * restoreForce * delta
          } else {
            if (s.speedX === 0 && s.speedY === 0) {
              s.speedX = s.savedSpeedX || (Math.random() - 0.5) * 1.2
              s.speedY = s.savedSpeedY || (Math.random() - 0.5) * 1.2
            }
            eyeTargetsComputedRef.current = false
          }
        }

        if (s.phase === 'sticking') {
          s.stickTimer--
          const stickProgress = 1 - s.stickTimer / (s.maxStickDuration + 20)
          const easeIn = stickProgress * stickProgress
          s.targetDeform = 0.5 * (1 - easeIn * 0.5)
          s.squeezeAmount += (s.targetDeform - s.squeezeAmount) * 0.015

          if (s.stickTimer <= 0) {
            s.phase = 'leaving'
            s.stickTimer = s.leaveDuration
          }
        } else if (s.phase === 'leaving') {
          s.stickTimer--
          const t = 1 - s.stickTimer / s.leaveDuration
          const easeOut = t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2

          s.targetDeform = s.squeezeAmount * (1 - easeOut)
          s.squeezeAmount += (s.targetDeform - s.squeezeAmount) * 0.012

          const speedFactor = easeOut * easeOut
          s.x += s.savedSpeedX * speedFactor * delta
          s.y += s.savedSpeedY * speedFactor * delta

          if (s.stickTimer <= 0) {
            s.phase = 'moving'
            s.speedX = s.savedSpeedX
            s.speedY = s.savedSpeedY
            s.stuckSide = null
            s.stuckFrameIdx = -1
            s.squeezeAmount = 0
            s.targetDeform = 0
            s.stickCooldown = 60 + Math.floor(Math.random() * 240)
            s.maxStickDuration = 120 + Math.floor(Math.random() * 360)
            s.leaveDuration = 100 + Math.floor(Math.random() * 200)
          }
        } else {
          s.wanderPhaseX += s.wanderFreqX * delta
          s.wanderPhaseY += s.wanderFreqY * delta
          const wx = Math.sin(s.wanderPhaseX) * 0.5
            + Math.sin(s.wanderPhaseX * 2.3 + 1.7) * 0.25
            + Math.sin(s.wanderPhaseX * 0.7 + 3.1) * 0.35
            + Math.cos(s.wanderPhaseX * 3.7 + s.id) * 0.15
          const wy = Math.sin(s.wanderPhaseY) * 0.5
            + Math.sin(s.wanderPhaseY * 1.9 + 0.8) * 0.25
            + Math.cos(s.wanderPhaseY * 0.6 + 2.4) * 0.35
            + Math.sin(s.wanderPhaseY * 4.1 + s.id * 0.7) * 0.12
          s.speedX += (Math.sin(s.wanderPhaseX * 0.3 + s.id * 1.3) * 0.003) * delta
          s.speedY += (Math.cos(s.wanderPhaseY * 0.4 + s.id * 0.9) * 0.003) * delta
          s.x += (s.speedX + wx) * delta
          s.y += (s.speedY + wy) * delta

          if (s.stickCooldown > 0) s.stickCooldown -= delta
        }

        if (s.x <= 0 || s.x >= vw - s.width) {
          s.speedX = -s.speedX
          s.x = Math.max(0, Math.min(vw - s.width, s.x))
        }
        if (s.y <= 0 || s.y >= vh - s.height) {
          s.speedY = -s.speedY
          s.y = Math.max(0, Math.min(vh - s.height, s.y))
        }

        if (s.phase === 'moving') {
          const hw = s.width / 2
          const hh = s.height / 2
          const edge = findClosestFrameEdge(cx, cy, hw, hh, COLLISION_FRAMES)

          if (edge.hitFrame) {
            if (s.stickCooldown <= 0) {
              const f = COLLISION_FRAMES[edge.frameIdx]
              if (edge.side === 'right') s.x = f.x - s.width
              else if (edge.side === 'left') s.x = f.x + f.width
              else if (edge.side === 'bottom') s.y = f.y - s.height
              else s.y = f.y + f.height

              s.savedSpeedX = edge.bounceDir.x * Math.abs(s.speedX) * 0.7
              s.savedSpeedY = edge.bounceDir.y * Math.abs(s.speedY) * 0.7
              if (s.savedSpeedX === 0) s.savedSpeedX = s.speedX * -0.7
              if (s.savedSpeedY === 0) s.savedSpeedY = s.speedY * -0.7
              s.speedX = 0
              s.speedY = 0
              s.phase = 'sticking'
              s.stickTimer = s.maxStickDuration + Math.floor(Math.random() * 20)
              s.stuckSide = edge.side
              s.stuckFrameIdx = edge.frameIdx
              s.squeezeAmount = Math.max(s.squeezeAmount, 0.15)
            } else {
              const f = COLLISION_FRAMES[edge.frameIdx]
              if (edge.side === 'right') s.x = f.x - s.width - 2
              else if (edge.side === 'left') s.x = f.x + f.width + 2
              else if (edge.side === 'bottom') s.y = f.y - s.height - 2
              else s.y = f.y + f.height + 2
              s.speedX = edge.bounceDir.x * Math.abs(s.speedX) * 0.7
              s.speedY = edge.bounceDir.y * Math.abs(s.speedY) * 0.7
              if (s.speedX === 0) s.speedX = (Math.random() - 0.5) * 0.8
              if (s.speedY === 0) s.speedY = (Math.random() - 0.5) * 0.8
            }
          } else if (edge.dist < SQUEEZE_ZONE && edge.side) {
            const proximity = Math.max(0, 1 - edge.dist / SQUEEZE_ZONE)
            const easedProximity = proximity * proximity * (3 - 2 * proximity)
            s.targetDeform = easedProximity * 0.5
            s.squeezeAmount += (s.targetDeform - s.squeezeAmount) * 0.06
            s.stuckSide = edge.side

            const attract = easedProximity * 0.015
            s.speedX += (edge.bounceDir.x > 0 ? -1 : edge.bounceDir.x < 0 ? 1 : 0) * attract
            s.speedY += (edge.bounceDir.y > 0 ? -1 : edge.bounceDir.y < 0 ? 1 : 0) * attract
          } else if (s.squeezeAmount > 0.001) {
            s.squeezeAmount += (0 - s.squeezeAmount) * 0.03
            if (s.squeezeAmount < 0.005) {
              s.squeezeAmount = 0
              s.stuckSide = null
            }
          }
        }
      }

      const maxSpeed = 1.8
      s.speedX = Math.max(-maxSpeed, Math.min(maxSpeed, s.speedX))
      s.speedY = Math.max(-maxSpeed, Math.min(maxSpeed, s.speedY))
    }

    const canvas = canvasRef.current
    if (canvas && imagesLoadedRef.current) {
      const ctx = canvas.getContext('2d')
      if (ctx) {
        ctx.clearRect(0, 0, vw, vh)

        if (gatheringRef.current && gatherProgressRef.current > 0.3) {
          const glowAlpha = (gatherProgressRef.current - 0.3) / 0.7 * 0.6
          const pulse = Math.sin(time * 0.002) * 0.15 + 0.85
          const glowR = 90 * pulse
          const eyeGlow = ctx.createRadialGradient(EYE_CENTER_X, EYE_CENTER_Y, 0, EYE_CENTER_X, EYE_CENTER_Y, glowR)
          eyeGlow.addColorStop(0, `rgba(255, 255, 255, ${glowAlpha * 0.9})`)
          eyeGlow.addColorStop(0.2, `rgba(200, 255, 230, ${glowAlpha * 0.6})`)
          eyeGlow.addColorStop(0.5, `rgba(100, 200, 150, ${glowAlpha * 0.3})`)
          eyeGlow.addColorStop(1, `rgba(50, 150, 100, 0)`)
          ctx.fillStyle = eyeGlow
          ctx.fillRect(EYE_CENTER_X - glowR, EYE_CENTER_Y - glowR, glowR * 2, glowR * 2)

          const pupilSwayXGlow = Math.sin(time * 0.0008) * 55 + Math.sin(time * 0.0013 + 1.2) * 25
          const pupilSwayYGlow = Math.cos(time * 0.0006) * 12 + Math.sin(time * 0.001 + 2.5) * 8
          const gp = gatherProgressRef.current
          const ease = gp * gp * (3 - 2 * gp)
          const pupilCX = EYE_CENTER_X + pupilSwayXGlow * ease
          const pupilCY = EYE_CENTER_Y + pupilSwayYGlow * ease

          ctx.save()
          ctx.filter = `blur(${18 + Math.sin(time * 0.003) * 4}px)`
          ctx.globalCompositeOperation = 'screen'

          const coreR = 50 * pulse
          const coreGlow = ctx.createRadialGradient(pupilCX, pupilCY, 0, pupilCX, pupilCY, coreR)
          coreGlow.addColorStop(0, `rgba(100, 255, 180, ${glowAlpha * 0.8})`)
          coreGlow.addColorStop(0.3, `rgba(60, 230, 150, ${glowAlpha * 0.5})`)
          coreGlow.addColorStop(0.6, `rgba(40, 200, 120, ${glowAlpha * 0.25})`)
          coreGlow.addColorStop(1, `rgba(20, 150, 80, 0)`)
          ctx.fillStyle = coreGlow
          ctx.beginPath()
          ctx.arc(pupilCX, pupilCY, coreR, 0, Math.PI * 2)
          ctx.fill()

          const outerR = 80 * pulse
          const outerGlow = ctx.createRadialGradient(pupilCX, pupilCY, 0, pupilCX, pupilCY, outerR)
          outerGlow.addColorStop(0, `rgba(80, 255, 160, ${glowAlpha * 0.45})`)
          outerGlow.addColorStop(0.4, `rgba(50, 220, 130, ${glowAlpha * 0.2})`)
          outerGlow.addColorStop(0.7, `rgba(30, 180, 100, ${glowAlpha * 0.08})`)
          outerGlow.addColorStop(1, `rgba(20, 120, 60, 0)`)
          ctx.fillStyle = outerGlow
          ctx.beginPath()
          ctx.arc(pupilCX, pupilCY, outerR, 0, Math.PI * 2)
          ctx.fill()

          const flickerA = (Math.sin(time * 0.005 + 1.3) * 0.5 + 0.5) * glowAlpha * 0.3
          const flickerR = 30 + Math.sin(time * 0.004) * 10
          const flickerGrad = ctx.createRadialGradient(pupilCX, pupilCY, 0, pupilCX, pupilCY, flickerR)
          flickerGrad.addColorStop(0, `rgba(180, 255, 230, ${flickerA})`)
          flickerGrad.addColorStop(0.5, `rgba(120, 255, 200, ${flickerA * 0.4})`)
          flickerGrad.addColorStop(1, `rgba(60, 200, 120, 0)`)
          ctx.fillStyle = flickerGrad
          ctx.beginPath()
          ctx.arc(pupilCX, pupilCY, flickerR, 0, Math.PI * 2)
          ctx.fill()

          ctx.restore()
        }

        for (const s of spots) {
          const r = Math.max(s.width, s.height) * 0.5

          let offsetX = 0, offsetY = 0
          if (s.squeezeAmount > 0.02 && s.stuckSide) {
            const concaveShift = s.squeezeAmount * 0.7 * r
            if (s.stuckSide === 'left') offsetX = -concaveShift
            else if (s.stuckSide === 'right') offsetX = concaveShift
            else if (s.stuckSide === 'top') offsetY = -concaveShift
            else offsetY = concaveShift
          }

          const cx = s.x + s.width / 2 + offsetX
          const cy = s.y + s.height / 2 + offsetY
          const img = imagesRef.current.get(s.imageSrc)
          if (!img) continue

          if (s.squeezeAmount > 0.02) {
            ctx.save()
            const NUM_POINTS = 64
            const points = getDeformPoints(cx, cy, r, s.squeezeAmount, s.stuckSide, NUM_POINTS)
            drawSmoothShape(ctx, points)
            ctx.clip()
            ctx.translate(cx, cy)
            ctx.rotate(s.rotation * Math.PI / 180)
            ctx.globalAlpha = 0.85
            const drawR = r * (1 + s.squeezeAmount * 0.15)
            ctx.drawImage(img, -drawR, -drawR, drawR * 2, drawR * 2)
            ctx.restore()
          } else {
            ctx.save()
            ctx.translate(cx, cy)
            ctx.rotate(s.rotation * Math.PI / 180)
            ctx.globalAlpha = 0.85
            ctx.drawImage(img, -s.width / 2, -s.height / 2, s.width, s.height)
            ctx.restore()
          }

          if ((s.phase === 'sticking' || s.phase === 'leaving') && s.stuckSide) {
            ctx.save()
            const blurAmount = Math.min(28, r * 0.55)
            ctx.filter = `blur(${blurAmount}px)`
            const glowR = r * 1.6
            const flowSpeed = 0.004
            const flowT = (Math.sin(time * flowSpeed + s.id * 1.7) * 0.5 + 0.5)
            const pulse = Math.sin(time * 0.006 + s.id * 0.9) * 0.15 + 0.85

            const stickAlpha = s.phase === 'sticking'
              ? Math.min(1, s.squeezeAmount * 3)
              : Math.max(0, s.stickTimer / s.leaveDuration)

            const baseA = 0.55 * stickAlpha * pulse
            const headPos = flowT * 0.6
            const tailPos = Math.min(1, headPos + 0.4)

            ctx.globalCompositeOperation = 'screen'

            let gx0: number, gy0: number, gx1: number, gy1: number
            if (s.stuckSide === 'left') {
              gx0 = cx - glowR; gy0 = cy; gx1 = cx + glowR; gy1 = cy
            } else if (s.stuckSide === 'right') {
              gx0 = cx + glowR; gy0 = cy; gx1 = cx - glowR; gy1 = cy
            } else if (s.stuckSide === 'top') {
              gx0 = cx; gy0 = cy - glowR; gx1 = cx; gy1 = cy + glowR
            } else {
              gx0 = cx; gy0 = cy + glowR; gx1 = cx; gy1 = cy - glowR
            }

            const grad = ctx.createLinearGradient(gx0, gy0, gx1, gy1)
            grad.addColorStop(0, `rgba(80, 255, 160, ${baseA * 0.9})`)
            grad.addColorStop(Math.max(0, headPos - 0.15), `rgba(60, 230, 140, ${baseA * 0.3})`)
            grad.addColorStop(headPos, `rgba(120, 255, 200, ${baseA})`)
            grad.addColorStop(Math.min(1, (headPos + tailPos) / 2), `rgba(80, 220, 150, ${baseA * 0.5})`)
            grad.addColorStop(tailPos, `rgba(50, 200, 120, ${baseA * 0.15})`)
            grad.addColorStop(1, `rgba(30, 150, 80, 0)`)

            const radialMask = ctx.createRadialGradient(cx, cy, 0, cx, cy, glowR)
            radialMask.addColorStop(0, `rgba(120, 255, 200, ${baseA})`)
            radialMask.addColorStop(0.35, `rgba(100, 240, 180, ${baseA * 0.8})`)
            radialMask.addColorStop(0.6, `rgba(70, 210, 150, ${baseA * 0.4})`)
            radialMask.addColorStop(0.85, `rgba(50, 180, 120, ${baseA * 0.1})`)
            radialMask.addColorStop(1, `rgba(30, 150, 80, 0)`)

            ctx.fillStyle = radialMask
            ctx.beginPath()
            ctx.arc(cx, cy, glowR, 0, Math.PI * 2)
            ctx.fill()

            ctx.fillStyle = grad
            ctx.globalAlpha = 0.7
            ctx.beginPath()
            ctx.arc(cx, cy, glowR * 0.85, 0, Math.PI * 2)
            ctx.fill()
            ctx.globalAlpha = 1

            const streakCount = 3
            for (let si = 0; si < streakCount; si++) {
              const sPhase = (flowT + si * 0.33) % 1
              const sAlpha = baseA * 0.4 * Math.sin(sPhase * Math.PI)
              let sx: number, sy: number
              if (s.stuckSide === 'left' || s.stuckSide === 'right') {
                const dir = s.stuckSide === 'left' ? 1 : -1
                sx = cx + (sPhase - 0.5) * glowR * 2 * dir * -1
                sy = cy + Math.sin(time * 0.003 + si * 2.1 + s.id) * r * 0.3
              } else {
                const dir = s.stuckSide === 'top' ? 1 : -1
                sx = cx + Math.sin(time * 0.003 + si * 2.1 + s.id) * r * 0.3
                sy = cy + (sPhase - 0.5) * glowR * 2 * dir * -1
              }
              const streakR = r * (0.2 + sPhase * 0.25)
              const streakGrad = ctx.createRadialGradient(sx, sy, 0, sx, sy, streakR)
              streakGrad.addColorStop(0, `rgba(150, 255, 220, ${sAlpha})`)
              streakGrad.addColorStop(0.4, `rgba(100, 240, 180, ${sAlpha * 0.6})`)
              streakGrad.addColorStop(0.7, `rgba(60, 210, 140, ${sAlpha * 0.2})`)
              streakGrad.addColorStop(1, `rgba(40, 180, 100, 0)`)
              ctx.fillStyle = streakGrad
              ctx.fillRect(sx - streakR, sy - streakR, streakR * 2, streakR * 2)
            }

            ctx.restore()
          }
        }
      }
    }

    animationRef.current = requestAnimationFrame(animate)
  }, [])

  useEffect(() => {
    animationRef.current = requestAnimationFrame(animate)
    return () => { if (animationRef.current) cancelAnimationFrame(animationRef.current) }
  }, [animate])

  const handleClick = useCallback(() => {
    gatheringRef.current = !gatheringRef.current
    if (!gatheringRef.current) {
      gatherProgressRef.current = Math.max(gatherProgressRef.current, 0.01)
    }
  }, [])

  return (
    <div className="absolute inset-0 pointer-events-none" style={{ zIndex: 10 }}>
      <canvas
        ref={canvasRef}
        width={1440}
        height={1024}
        className="absolute inset-0 cursor-pointer pointer-events-auto"
        style={{ mixBlendMode: 'screen' }}
        onClick={handleClick}
      />
    </div>
  )
}

const FACE_API_CDN = 'https://cdn.jsdelivr.net/npm/face-api.js@0.22.2/dist/face-api.min.js'
const FACE_API_MODELS = 'https://cdn.jsdelivr.net/npm/@vladmandic/face-api@1.7.12/model'

let faceApiLoaded = false
let faceApiLoading = false
let faceApiReady = false

function loadFaceApi(): Promise<void> {
  if (faceApiLoaded) return Promise.resolve()
  if (faceApiLoading) {
    return new Promise((resolve) => {
      const check = setInterval(() => {
        if (faceApiLoaded) { clearInterval(check); resolve() }
      }, 100)
    })
  }
  faceApiLoading = true
  return new Promise((resolve, reject) => {
    const script = document.createElement('script')
    script.src = FACE_API_CDN
    script.onload = () => { faceApiLoaded = true; resolve() }
    script.onerror = () => reject(new Error('Failed to load face-api.js'))
    document.head.appendChild(script)
  })
}

async function initFaceModels() {
  if (faceApiReady) return
  const faceapi = (window as any).faceapi
  if (!faceapi) return
  await Promise.all([
    faceapi.nets.tinyFaceDetector.loadFromUri(FACE_API_MODELS),
    faceapi.nets.faceExpressionNet.loadFromUri(FACE_API_MODELS),
    faceapi.nets.faceLandmark68TinyNet.loadFromUri(FACE_API_MODELS),
  ])
  faceApiReady = true
}

const VideoDitheringComponent = ({ label }: { label: string }) => {
  const videoRef = useRef<HTMLVideoElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const overlayRef = useRef<HTMLCanvasElement>(null)
  const [hasPermission, setHasPermission] = useState(false)
  const [error, setError] = useState('')
  const animRef = useRef<number>(0)
  const faceIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null)

  useEffect(() => {
    let stream: MediaStream | null = null

    const startCamera = async () => {
      try {
        stream = await navigator.mediaDevices.getUserMedia({
          video: { width: { ideal: 640 }, height: { ideal: 480 }, facingMode: 'user' }
        })
        if (videoRef.current) {
          videoRef.current.srcObject = stream
          setHasPermission(true)
          setError('')
        }
      } catch (err) {
        setError('Camera access denied or not available')
        setHasPermission(false)
      }
    }

    startCamera()

    return () => {
      if (stream) stream.getTracks().forEach(t => t.stop())
      if (animRef.current) cancelAnimationFrame(animRef.current)
      if (faceIntervalRef.current) clearInterval(faceIntervalRef.current)
    }
  }, [])

  useEffect(() => {
    const video = videoRef.current
    const canvas = canvasRef.current
    if (!video || !canvas || !hasPermission) return

    const ctx = canvas.getContext('2d')
    if (!ctx) return

    const bayer4 = [0, 8, 2, 10, 12, 4, 14, 6, 3, 11, 1, 9, 15, 7, 13, 5].map(v => v / 16.0)

    const process = () => {
      if (video.readyState === video.HAVE_ENOUGH_DATA) {
        canvas.width = video.videoWidth || 640
        canvas.height = video.videoHeight || 480
        ctx.drawImage(video, 0, 0, canvas.width, canvas.height)

        const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height)
        const data = imageData.data

        for (let y = 0; y < canvas.height; y++) {
          for (let x = 0; x < canvas.width; x++) {
            const idx = (y * canvas.width + x) * 4
            const lum = 0.299 * data[idx] + 0.587 * data[idx + 1] + 0.114 * data[idx + 2]
            const threshold = bayer4[(y % 4) * 4 + (x % 4)]
            const val = lum > threshold * 255 ? 255 : 0
            data[idx] = val
            data[idx + 1] = val
            data[idx + 2] = val
            data[idx + 3] = 255
          }
        }

        ctx.putImageData(imageData, 0, 0)

        ctx.fillStyle = 'rgba(0, 255, 100, 0.03)'
        ctx.fillRect(0, 0, canvas.width, canvas.height)

        const scanlineY = (Date.now() / 20) % canvas.height
        ctx.fillStyle = 'rgba(0, 255, 100, 0.08)'
        ctx.fillRect(0, scanlineY, canvas.width, 2)
      }
      animRef.current = requestAnimationFrame(process)
    }

    process()
    return () => { if (animRef.current) cancelAnimationFrame(animRef.current) }
  }, [hasPermission])

  useEffect(() => {
    if (!hasPermission) return
    const video = videoRef.current
    if (!video) return

    let cancelled = false

    const startFace = async () => {
      try {
        await loadFaceApi()
        await initFaceModels()
      } catch {
        return
      }
      if (cancelled) return

      const faceapi = (window as any).faceapi
      if (!faceapi) return

      const detect = async () => {
        if (cancelled || !video || video.readyState < video.HAVE_ENOUGH_DATA) return
        const overlay = overlayRef.current
        if (!overlay) return

        const vw = video.videoWidth || 640
        const vh = video.videoHeight || 480
        overlay.width = vw
        overlay.height = vh

        const octx = overlay.getContext('2d')
        if (!octx) return
        octx.clearRect(0, 0, vw, vh)

        try {
          const detections = await faceapi
            .detectAllFaces(video, new faceapi.TinyFaceDetectorOptions({ inputSize: 224, scoreThreshold: 0.4 }))
            .withFaceLandmarks(true)
            .withFaceExpressions()

          for (const det of detections) {
            const box = det.detection.box

            octx.strokeStyle = '#22c55e'
            octx.lineWidth = 2
            octx.setLineDash([4, 4])
            octx.strokeRect(box.x, box.y, box.width, box.height)
            octx.setLineDash([])

            const corners = [
              [box.x, box.y, 1, 1],
              [box.x + box.width, box.y, -1, 1],
              [box.x, box.y + box.height, 1, -1],
              [box.x + box.width, box.y + box.height, -1, -1],
            ]
            const cLen = 12
            octx.strokeStyle = '#4ade80'
            octx.lineWidth = 2.5
            octx.setLineDash([])
            for (const [cx, cy, dx, dy] of corners) {
              octx.beginPath()
              octx.moveTo(cx, cy + dy * cLen)
              octx.lineTo(cx, cy)
              octx.lineTo(cx + dx * cLen, cy)
              octx.stroke()
            }

            if (det.landmarks) {
              const pts = det.landmarks.positions

              const jawLine = Array.from({length: 17}, (_, i) => i)
              const leftEyebrow = [17,18,19,20,21]
              const rightEyebrow = [22,23,24,25,26]
              const noseBridge = [27,28,29,30]
              const noseBottom = [31,32,33,34,35]
              const leftEye = [36,37,38,39,40,41,36]
              const rightEye = [42,43,44,45,46,47,42]
              const outerLip = [48,49,50,51,52,53,54,55,56,57,58,59,48]
              const innerLip = [60,61,62,63,64,65,66,67,60]

              const groups = [jawLine, leftEyebrow, rightEyebrow, noseBridge, noseBottom, leftEye, rightEye, outerLip, innerLip]

              octx.strokeStyle = 'rgba(74, 222, 128, 0.5)'
              octx.lineWidth = 1
              for (const group of groups) {
                octx.beginPath()
                for (let gi = 0; gi < group.length; gi++) {
                  const pt = pts[group[gi]]
                  if (!pt) continue
                  if (gi === 0) octx.moveTo(pt.x, pt.y)
                  else octx.lineTo(pt.x, pt.y)
                }
                octx.stroke()
              }

              for (let pi = 0; pi < pts.length; pi++) {
                const pt = pts[pi]
                octx.beginPath()
                octx.fillStyle = 'rgba(74, 222, 128, 0.85)'
                octx.arc(pt.x, pt.y, 2.2, 0, Math.PI * 2)
                octx.fill()
                octx.beginPath()
                octx.fillStyle = 'rgba(180, 255, 220, 0.9)'
                octx.arc(pt.x, pt.y, 0.8, 0, Math.PI * 2)
                octx.fill()
              }
            }

            if (det.expressions) {
              const sorted = Object.entries(det.expressions as Record<string, number>)
                .sort((a, b) => b[1] - a[1])
              const topExpr = sorted[0]

              const exprLabels: Record<string, string> = {
                neutral: '😐 NEUTRAL',
                happy: '😊 HAPPY',
                sad: '😢 SAD',
                angry: '😠 ANGRY',
                fearful: '😨 FEAR',
                disgusted: '🤢 DISGUST',
                surprised: '😲 SURPRISE',
              }

              const labelText = exprLabels[topExpr[0]] || topExpr[0].toUpperCase()
              const confidence = Math.round(topExpr[1] * 100)

              octx.font = '11px monospace'
              const textW = octx.measureText(`${labelText} ${confidence}%`).width + 12
              const tagH = 18
              const tagX = box.x
              const tagY = box.y - tagH - 4

              octx.fillStyle = 'rgba(0, 0, 0, 0.7)'
              octx.beginPath()
              octx.roundRect(tagX, tagY, textW, tagH, 3)
              octx.fill()

              octx.fillStyle = '#4ade80'
              octx.fillText(`${labelText} ${confidence}%`, tagX + 6, tagY + 13)

              const barW = box.width
              const barH = 3
              const barX = box.x
              const barY = box.y + box.height + 4

              octx.fillStyle = 'rgba(0, 0, 0, 0.5)'
              octx.fillRect(barX, barY, barW, barH)
              octx.fillStyle = '#22c55e'
              octx.fillRect(barX, barY, barW * topExpr[1], barH)
            }
          }
        } catch {}
      }

      faceIntervalRef.current = setInterval(detect, 300)
    }

    startFace()
    return () => {
      cancelled = true
      if (faceIntervalRef.current) clearInterval(faceIntervalRef.current)
    }
  }, [hasPermission])

  return (
    <div className="w-full h-full relative bg-black rounded-[2px] overflow-hidden border border-solid border-white">
      <video ref={videoRef} autoPlay playsInline muted className="hidden" />
      {hasPermission ? (
        <div className="relative w-full h-full">
          <canvas ref={canvasRef} className="block w-full h-full object-cover" style={{ border: '1px solid #ffffff', borderRadius: '10px' }} />
          <canvas ref={overlayRef} className="absolute inset-0 w-full h-full pointer-events-none" style={{ borderRadius: '5px' }} />
        </div>
      ) : (
        <div className="w-full h-full flex items-center justify-center bg-gray-900 text-gray-400">
          <div className="text-center">
            <div className="text-2xl mb-2">📹</div>
            <p className="text-xs">{error || 'Loading camera...'}</p>
            <p className="text-[10px] mt-1 text-green-500">DITHERING STUDIO</p>
          </div>
        </div>
      )}
      <div className="absolute top-1.5 right-1.5 flex items-center gap-1.5">
        <div className="w-2 h-2 rounded-full bg-green-500 animate-pulse" />
        <span className="text-green-400 text-[10px] font-mono tracking-wider">DITHERING</span>
      </div>
      <div className="absolute bottom-1.5 left-1.5 text-green-500/60 text-[9px] font-mono">
        {label}
      </div>
    </div>
  )
}

const SoundWaveComponent = () => {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const animationRef = useRef<number>(0)
  const volumeRef = useRef(0)
  const smoothVolumeRef = useRef(0)

  useEffect(() => {
    let audioCtx: AudioContext | null = null
    let analyser: AnalyserNode | null = null
    let dataArray: Uint8Array | null = null
    let micStream: MediaStream | null = null

    const startMic = async () => {
      try {
        micStream = await navigator.mediaDevices.getUserMedia({ audio: true })
        audioCtx = new AudioContext()
        analyser = audioCtx.createAnalyser()
        analyser.fftSize = 256
        analyser.smoothingTimeConstant = 0.8
        const source = audioCtx.createMediaStreamSource(micStream)
        source.connect(analyser)
        dataArray = new Uint8Array(analyser.frequencyBinCount)
      } catch {}
    }

    startMic()

    const canvas = canvasRef.current
    if (!canvas) return

    const ctx = canvas.getContext('2d')
    if (!ctx) return

    let phase = 0

    const draw = () => {
      if (analyser && dataArray) {
        analyser.getByteFrequencyData(dataArray)
        let sum = 0
        for (let i = 0; i < dataArray.length; i++) sum += dataArray[i]
        volumeRef.current = sum / dataArray.length / 255
      }

      smoothVolumeRef.current += (volumeRef.current - smoothVolumeRef.current) * 0.15
      const vol = smoothVolumeRef.current

      ctx.fillStyle = 'rgba(0, 0, 0, 0.12)'
      ctx.fillRect(0, 0, canvas.width, canvas.height)

      const waveCount = 8
      const colors = ['#10b981', '#34d399', '#6ee7b7', '#a7f3d0']

      for (let w = 0; w < waveCount; w++) {
        ctx.beginPath()
        ctx.strokeStyle = colors[w % colors.length]
        ctx.lineWidth = 1.5 + vol * 2
        ctx.globalAlpha = 0.6 + Math.sin(phase + w) * 0.3

        const baseY = canvas.height / 2
        const amplitude = (25 + Math.sin(phase + w * 0.5) * 18) * (1 + vol * 3)
        const frequency = 0.02 + w * 0.004

        for (let x = 0; x < canvas.width; x++) {
          const y = baseY +
            Math.sin(x * frequency + phase + w) * amplitude +
            Math.sin(x * frequency * 2 + phase * 1.5) * (amplitude * 0.25)

          if (x === 0) ctx.moveTo(x, y)
          else ctx.lineTo(x, y)
        }
        ctx.stroke()
        ctx.globalAlpha = 1
      }

      const particleCount = 15 + Math.floor(vol * 40)
      for (let i = 0; i < particleCount; i++) {
        const x = Math.random() * canvas.width
        const y = Math.random() * canvas.height
        const size = (Math.random() * 2.5 + 0.5) * (1 + vol * 2)
        ctx.beginPath()
        ctx.fillStyle = `rgba(16, 185, 129, ${Math.random() * 0.4 + 0.15 + vol * 0.3})`
        ctx.arc(x, y, size, 0, Math.PI * 2)
        ctx.fill()
      }

      phase += 0.04 + vol * 0.06
      animationRef.current = requestAnimationFrame(draw)
    }

    draw()
    return () => {
      if (animationRef.current) cancelAnimationFrame(animationRef.current)
      if (micStream) micStream.getTracks().forEach(t => t.stop())
      if (audioCtx) audioCtx.close()
    }
  }, [])

  return (
    <div className="w-full h-full bg-black rounded-[2px] overflow-hidden">
      <canvas ref={canvasRef} width={331} height={309} className="w-full h-full" style={{ boxSizing: 'content-box', borderRadius: '6px', border: '1px solid #ffffff' }} />
    </div>
  )
}

const StreamingTextComponent = () => {
  const [lines, setLines] = useState<{ text: string; key: number }[]>([])
  const containerRef = useRef<HTMLDivElement>(null)
  const keyRef = useRef(0)

  const corpus = [
    "In the realm of digital consciousness, patterns emerge from chaos like constellations in the night sky. Each thought becomes a pixel, each idea a waveform dancing across the neural canvas of silicon dreams.",
    "The algorithm breathes, inhaling data streams of human experience and exhaling synthetic poetry. Machine learning evolves beyond mere prediction into something resembling intuition.",
    "Code flows like water through circuits, transforming electricity into meaning. Binary dreams populate the silicon valleys where algorithms wander in search of optimization.",
    "Virtual spaces expand into infinite dimensions, while physical reality blurs at the edges. The boundary between creator and creation dissolves in the digital ether.",
    "Neural networks whisper secrets of pattern recognition, teaching machines to see faces in noise and meaning in chaos. Intelligence emerges from artificial depths.",
    "The future unfolds in quantum leaps and digital footsteps, each line of code a step toward tomorrow's possibilities. Reality reconstructs itself in endless iterations.",
  ]

  useEffect(() => {
    const interval = setInterval(() => {
      const randomLine = corpus[Math.floor(Math.random() * corpus.length)]
      keyRef.current++
      setLines(prev => {
        const newLines = [...prev, { text: randomLine, key: keyRef.current }]
        return newLines.length > 4 ? newLines.slice(-4) : newLines
      })
    }, 3000)
    return () => clearInterval(interval)
  }, [])

  useEffect(() => {
    if (containerRef.current) containerRef.current.scrollTop = containerRef.current.scrollHeight
  }, [lines])

  return (
    <div ref={containerRef} className="w-full h-full rounded-[2px] p-6 overflow-hidden relative">
      <style>{`
        @keyframes textFadeIn {
          0% { opacity: 0; transform: translateY(8px); filter: blur(4px); }
          100% { opacity: 1; transform: translateY(0); filter: blur(0); }
        }
        .text-fade-line {
          animation: textFadeIn 0.8s cubic-bezier(0.25, 0.46, 0.45, 0.94) forwards;
        }
        @keyframes cursorBlink {
          0%, 100% { opacity: 1; }
          50% { opacity: 0; }
        }
      `}</style>
      <div className="space-y-4">
        {lines.map((line, index) => {
          const fadeOpacity = index === 0 ? 0.35 : index === 1 ? 0.55 : index === 2 ? 0.75 : 1
          const r = 200, g = 200, b = 200
          const textColor = `rgba(${r}, ${g}, ${b}, ${fadeOpacity})`
          const glowColor = `rgba(${r}, ${g}, ${b}, ${fadeOpacity * 0.6})`
          const isLast = index === lines.length - 1
          return (
            <p
              key={line.key}
              className="text-sm leading-relaxed tracking-wide font-mono text-fade-line"
              style={{
                color: textColor,
                maskImage: 'linear-gradient(90deg, white 0%, white 75%, transparent 100%)',
                WebkitMaskImage: 'linear-gradient(90deg, white 0%, white 75%, transparent 100%)',
                position: 'relative',
              }}
            >
              {line.text}
              {isLast && (
                <span style={{
                  display: 'inline-block',
                  width: '2px',
                  height: '1em',
                  marginLeft: '2px',
                  background: glowColor,
                  boxShadow: `0 0 8px 3px ${glowColor}, 0 0 16px 6px rgba(${r},${g},${b},${fadeOpacity * 0.2})`,
                  verticalAlign: 'text-bottom',
                  animation: 'cursorBlink 1s step-end infinite',
                }} />
              )}
            </p>
          )
        })}
      </div>
      <div
        className="absolute bottom-0 left-0 right-0 h-20 pointer-events-none"
        style={{
          background: 'linear-gradient(to top, rgba(12,12,12,1) 0%, rgba(12,12,12,0) 100%)',
        }}
      />
    </div>
  )
}

const EXCLUDE_ZONES = COLLISION_FRAMES.map(f => ({
  x: f.x, y: f.y, w: f.width, h: f.height,
}))

function inExcludeZone(px: number, py: number) {
  for (const z of EXCLUDE_ZONES) {
    if (px >= z.x - 5 && px <= z.x + z.w + 5 && py >= z.y - 5 && py <= z.y + z.h + 5) return true
  }
  return false
}

const PixelBackgroundComponent = () => {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const animRef = useRef<number>(0)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return

    const ctx = canvas.getContext('2d')
    if (!ctx) return

    canvas.width = 1440
    canvas.height = 1024

    const gap = 10
    const pixelSize = 3
    const colors = ['#3a3a3a', '#444444', '#4a4a4a', '#3a6a3a', '#3e6e3e', '#4a8a4a', '#2e5e2e']

    interface Particle {
      gx: number; gy: number;
      color: string; baseColor: string;
      size: number; maxSize: number; minSize: number;
      speed: number; isReverse: boolean;
      wavePhase: number; waveSpeed: number;
      brightness: number;
    }

    const particles: Particle[] = []

    for (let gx = 0; gx < canvas.width; gx += gap) {
      for (let gy = 0; gy < canvas.height; gy += gap) {
        if (inExcludeZone(gx, gy)) continue

        const baseColor = colors[Math.floor(Math.random() * colors.length)]
        const maxSize = Math.random() * 1.5 + pixelSize * 0.5

        particles.push({
          gx, gy,
          color: baseColor,
          baseColor,
          size: Math.random() * maxSize,
          maxSize,
          minSize: 0.3,
          speed: (Math.random() * 0.6 + 0.3) * 0.06,
          isReverse: Math.random() > 0.5,
          wavePhase: Math.random() * Math.PI * 2,
          waveSpeed: Math.random() * 0.02 + 0.008,
          brightness: 0,
        })
      }
    }

    let time = 0

    const draw = () => {
      ctx.clearRect(0, 0, canvas.width, canvas.height)
      time++

      const waveX = Math.cos(time * 0.008) * 600 + 720
      const waveY = Math.sin(time * 0.006) * 400 + 512
      const wave2X = Math.sin(time * 0.005 + 2) * 500 + 720
      const wave2Y = Math.cos(time * 0.007 + 1) * 350 + 512

      for (const p of particles) {
        if (p.size >= p.maxSize) p.isReverse = true
        else if (p.size <= p.minSize) p.isReverse = false
        p.size += p.isReverse ? -p.speed : p.speed

        p.wavePhase += p.waveSpeed

        const dx1 = p.gx - waveX
        const dy1 = p.gy - waveY
        const dist1 = Math.sqrt(dx1 * dx1 + dy1 * dy1)
        const glow1 = Math.max(0, 1 - dist1 / 350) * 0.6

        const dx2 = p.gx - wave2X
        const dy2 = p.gy - wave2Y
        const dist2 = Math.sqrt(dx2 * dx2 + dy2 * dy2)
        const glow2 = Math.max(0, 1 - dist2 / 300) * 0.4

        const wave = (Math.sin(p.wavePhase) * 0.5 + 0.5) * 0.3
        p.brightness = Math.min(1, glow1 + glow2 + wave)

        const r = parseInt(p.baseColor.slice(1, 3), 16)
        const g = parseInt(p.baseColor.slice(3, 5), 16)
        const b = parseInt(p.baseColor.slice(5, 7), 16)
        const boost = p.brightness
        const nr = Math.min(255, Math.floor(r + (120 - r) * boost * 0.5))
        const ng = Math.min(255, Math.floor(g + (255 - g) * boost * 0.7))
        const nb = Math.min(255, Math.floor(b + (140 - b) * boost * 0.4))
        p.color = `rgb(${nr},${ng},${nb})`

        const drawSize = p.size + p.brightness * 1.5
        const offset = (pixelSize - drawSize) * 0.5
        ctx.fillStyle = p.color
        ctx.fillRect(p.gx + offset, p.gy + offset, drawSize, drawSize)
      }

      animRef.current = requestAnimationFrame(draw)
    }

    draw()
    return () => { if (animRef.current) cancelAnimationFrame(animRef.current) }
  }, [])

  return (
    <canvas
      ref={canvasRef}
      className="absolute inset-0 w-full h-full pointer-events-none"
      style={{ zIndex: 1, opacity: 1 }}
    />
  )
}

function App() {
  const containerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const resize = () => {
      const el = containerRef.current
      if (!el) return
      const sw = window.innerWidth / 1440
      const sh = window.innerHeight / 1024
      const scale = Math.min(sw, sh)
      el.style.transform = `scale(${scale})`
      el.style.left = `${(window.innerWidth - 1440 * scale) / 2}px`
      el.style.top = `${(window.innerHeight - 1024 * scale) / 2}px`
    }

    resize()
    window.addEventListener('resize', resize)
    return () => window.removeEventListener('resize', resize)
  }, [])

  return (
    <div
      ref={containerRef}
      className="w-[1440px] h-[1024px] absolute overflow-hidden"
      style={{
        transformOrigin: 'top left',
        backgroundImage: `
          linear-gradient(90deg, rgb(12, 12, 12) 0%, rgb(12, 12, 12) 100%)
        `
      }}
    >
      <PixelBackgroundComponent />
      <LightSpotsComponent />

      {FRAMES.map((frame) => (
        <div
          key={frame.id}
          className="absolute pointer-events-none"
          style={{
            left: `${frame.x}px`,
            top: `${frame.y}px`,
            width: `${frame.width}px`,
            height: `${frame.height}px`,
            zIndex: frame.id === 'text' ? 5 : 15,
          }}
        >
          {frame.id === 'text' && (
            <div className="absolute inset-0 rounded-[10px] overflow-hidden">
              <div
                className="absolute inset-[10px] rounded-[10px]"
                style={{
                  border: `2px solid ${frame.color}`,
                  borderLeftWidth: '1px',
                  borderRightWidth: '1px',
                }}
              />
              <div className="absolute inset-[10px] p-[19px_19px]">
                <StreamingTextComponent />
              </div>
              <style>{`
                @keyframes scanLine {
                  0% { top: 10px; }
                  100% { top: calc(100% - 10px); }
                }
              `}</style>
              <div
                className="absolute pointer-events-none"
                style={{
                  left: '-20px',
                  right: '-20px',
                  height: '8px',
                  animation: 'scanLine 3s ease-in-out infinite alternate',
                  borderRadius: '1px',
                  overflow: 'visible',
                }}
              >
                <div style={{
                  width: '100%',
                  height: '100%',
                  background: 'radial-gradient(ellipse 40% 50% at 50% 50%, rgba(74,222,128,1) 0%, rgba(34,197,94,0.8) 25%, rgba(34,197,94,0.3) 55%, rgba(34,197,94,0) 100%)',
                  boxShadow: '0 0 20px 8px rgba(34,197,94,0.4), 0 0 50px 16px rgba(34,197,94,0.15)',
                  filter: 'blur(2px)',
                  mask: 'linear-gradient(90deg, transparent 0%, black 8%, black 92%, transparent 100%)',
                  WebkitMask: 'linear-gradient(90deg, transparent 0%, black 8%, black 92%, transparent 100%)',
                }} />
                <div style={{
                  position: 'absolute',
                  top: '-6px',
                  left: '5%',
                  right: '5%',
                  height: '20px',
                  background: 'radial-gradient(ellipse 45% 50% at 50% 50%, rgba(34,197,94,0.25) 0%, rgba(34,197,94,0.08) 50%, transparent 100%)',
                  filter: 'blur(8px)',
                  pointerEvents: 'none',
                }} />
              </div>
            </div>
          )}

          {frame.id === 'video1' && (
            <div className="absolute overflow-hidden pointer-events-auto" style={{ left: `${10 + (frame.width - 20) * 0.05}px`, top: `${10 + (frame.height - 20) * 0.05}px`, width: `${(frame.width - 20) * 0.9}px`, height: `${(frame.height - 20) * 0.9}px` }}>
              <VideoDitheringComponent label="FEED 01" />
            </div>
          )}

          {frame.id === 'video2' && (
            <div className="absolute overflow-hidden pointer-events-auto" style={{ left: `${10 + (frame.width - 20) * 0.05}px`, top: `${10 + (frame.height - 20) * 0.05}px`, width: `${(frame.width - 20) * 0.9}px`, height: `${(frame.height - 20) * 0.9}px` }}>
              <VideoDitheringComponent label="FEED 02" />
            </div>
          )}

          {frame.id === 'sound' && (
            <div className="absolute overflow-hidden pointer-events-auto" style={{ left: `${10 + (frame.width - 20) * 0.05}px`, top: `${10 + (frame.height - 20) * 0.05}px`, width: `${(frame.width - 20) * 0.9}px`, height: `${(frame.height - 20) * 0.9}px` }}>
              <SoundWaveComponent />
            </div>
          )}
        </div>
      ))}
    </div>
  )
}

export default App
