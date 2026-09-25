import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { SmokeApp } from './SmokeApp'
import '../../../styles/fonts.css'
import '../../../styles/tokens.css'
import '../../../styles/global.css'
import '../../../styles/card.css'

createRoot(document.getElementById('root')!).render(<StrictMode><SmokeApp /></StrictMode>)
