import React from 'react';
import { createRoot } from 'react-dom/client';
import App from './app/App';
import './styles/app.css';

const el = document.getElementById('root');
if (!el) throw new Error('Root element missing');
createRoot(el).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
