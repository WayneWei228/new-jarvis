import { useState, useEffect } from 'react'

const LightSpot = ({ 
  src, 
  className, 
  initialX, 
  initialY, 
  size,
  rotation,
  animationDuration,
  animationDelay 
}: { 
  src: string
  className?: string
  initialX: number
  initialY: number
  size: number
  rotation: number
  animationDuration: number
  animationDelay: number
}) => {
  return (
    <div
      className={`absolute ${className}`}
      style={{
        left: `${initialX}px`,
        top: `${initialY}px`,
        width: `${size}px`,
        height: `${size}px`,
        animation: `float ${animationDuration}s ease-in-out infinite`,
        animationDelay: `${animationDelay}s`,
        transform: `rotate(${rotation}deg)`
      }}
    >
      <img 
        src={src} 
        alt=""
        className="w-full h-full object-contain"
      />
    </div>
  )
}

function AnimationEffect() {
  const [mounted, setMounted] = useState(false)

  useEffect(() => {
    setMounted(true)
  }, [])

  const lightSpots = [
    {
      src: "http://localhost:3845/assets/aa271892e2dcf67550ae6aa81f7f7f7e10ecfbb2.png",
      initialX: 177.5,
      initialY: 472.6,
      size: 147,
      rotation: 14.92,
      animationDuration: 4,
      animationDelay: 0
    },
    {
      src: "http://localhost:3845/assets/391b0bb151240876eaee387b8249d0b8eb345486.svg",
      initialX: 184,
      initialY: 336.3,
      size: 134.5,
      rotation: -37.56,
      animationDuration: 5,
      animationDelay: 0.5
    },
    {
      src: "http://localhost:3845/assets/de663f1e8f8d5e3bb71e1ec1afd55c6e13d63d1a.svg",
      initialX: 390.2,
      initialY: 613.8,
      size: 133.6,
      rotation: -145.88,
      animationDuration: 4.5,
      animationDelay: 1
    },
    {
      src: "http://localhost:3845/assets/90e876ef2e9417b9d0b6f5d910323e94e714ecca.svg",
      initialX: 530.7,
      initialY: 673.3,
      size: 122.6,
      rotation: 162.84,
      animationDuration: 5.5,
      animationDelay: 1.5
    },
    {
      src: "http://localhost:3845/assets/522a7f9b198eb3e1dab8552e0257c013e322ddc2.svg",
      initialX: 204.8,
      initialY: 427.9,
      size: 134.8,
      rotation: 136.25,
      animationDuration: 4,
      animationDelay: 0.3
    },
    {
      src: "http://localhost:3845/assets/522a7f9b198eb3e1dab8552e0257c013e322ddc2.svg",
      initialX: 496.8,
      initialY: 385.9,
      size: 134.8,
      rotation: 136.25,
      animationDuration: 5,
      animationDelay: 0.8
    },
    {
      src: "http://localhost:3845/assets/1cbe3073fba9a0a7ff1d5e344c83caaf27f854cd.svg",
      initialX: 593.0,
      initialY: 476.3,
      size: 129.3,
      rotation: 154.7,
      animationDuration: 4.2,
      animationDelay: 1.2
    },
    {
      src: "http://localhost:3845/assets/0f97cd846e14f1a7c65096a24b5177ae2a81a1aa.svg",
      initialX: 742.4,
      initialY: 576.6,
      size: 126.4,
      rotation: 158.53,
      animationDuration: 4.8,
      animationDelay: 0.7
    },
    {
      src: "http://localhost:3845/assets/522a7f9b198eb3e1dab8552e0257c013e322ddc2.svg",
      initialX: 733.8,
      initialY: 384.9,
      size: 134.8,
      rotation: 136.25,
      animationDuration: 5.2,
      animationDelay: 1.8
    }
  ]

  return (
    <div className="w-full min-h-screen bg-[#0c0c0c] relative overflow-hidden">
      <style>
        {`
          @keyframes float {
            0%, 100% {
              transform: translateY(0) rotate(var(--rotation, 0deg));
              opacity: 0.8;
            }
            50% {
              transform: translateY(-30px) rotate(calc(var(--rotation, 0deg) + 5deg));
              opacity: 1;
            }
          }
          
          @keyframes pulse {
            0%, 100% {
              transform: scale(1);
              opacity: 0.7;
            }
            50% {
              transform: scale(1.1);
              opacity: 1;
            }
          }
          
          @keyframes glow {
            0%, 100% {
              filter: brightness(1) blur(0px);
            }
            50% {
              filter: brightness(1.3) blur(2px);
            }
          }
          
          .light-spot {
            animation: float 4s ease-in-out infinite, glow 3s ease-in-out infinite;
          }
        `}
      </style>
      
      {mounted && lightSpots.map((spot, index) => (
        <div
          key={index}
          className="light-spot absolute"
          style={{
            left: `${spot.initialX}px`,
            top: `${spot.initialY}px`,
            width: `${spot.size}px`,
            height: `${spot.size}px`,
            animationDelay: `${spot.animationDelay}s`,
            '--rotation': `${spot.rotation}deg`
          } as React.CSSProperties}
        >
          <div 
            className="w-full h-full"
            style={{ 
              transform: `rotate(${spot.rotation}deg)`,
              animation: `pulse ${spot.animationDuration}s ease-in-out infinite`,
              animationDelay: `${spot.animationDelay}s`
            }}
          >
            <img 
              src={spot.src} 
              alt=""
              className="w-full h-full object-contain"
            />
          </div>
        </div>
      ))}
    </div>
  )
}

export default AnimationEffect
