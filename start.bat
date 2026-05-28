@echo off
title Quality Control HQ

echo ============================================
echo  Starting Backend ^& Frontend...
echo ============================================

start "Backend (Django)" cmd /k ".venv\Scripts\activate && python backend\manage.py runserver"
timeout /t 3 /nobreak > nul
start "Frontend (Vite)" cmd /k "cd frontend && npm run dev"

echo ============================================
echo  Backend  : http://127.0.0.1:8000
echo  Frontend : http://localhost:5173
echo ============================================
