if __name__ == "__main__":
    try:
        from app.scheduler import Scheduler
        Scheduler().run()
    except KeyboardInterrupt: print("Bot parado.")
    except Exception as e: print(f"Erro fatal: {e}"); raise
