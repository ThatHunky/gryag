#!/bin/bash

# Gryag Bot Setup and Optimization Script
# Fixes Redis issues, optimizes configuration, and provides health checks

set -e

echo "🔧 Gryag Bot Setup and Optimization"
echo "=================================="

# Function to check if Docker is running
check_docker() {
    if ! docker info > /dev/null 2>&1; then
        echo "❌ Docker is not running. Please start Docker first."
        exit 1
    fi
    echo "✅ Docker is running"
}

# Function to check if .env file exists
check_env() {
    if [ ! -f .env ]; then
        echo "⚠️  .env file not found"
        if [ -f .env.example ]; then
            echo "📋 Copying .env.example to .env"
            cp .env.example .env
            echo "⚠️  Please edit .env file with your tokens before running the bot"
        else
            echo "❌ No .env.example found. Please create .env manually."
            exit 1
        fi
    else
        echo "✅ .env file found"
    fi
}

# Function to optimize environment for resource efficiency
optimize_env() {
    echo "⚡ Applying resource optimizations to .env"
    
    # Create backup
    cp .env .env.backup
    
    # Apply optimizations
    sed -i 's/^ENABLE_PROFILE_SUMMARIZATION=.*/ENABLE_PROFILE_SUMMARIZATION=false/' .env
    sed -i 's/^FACT_EXTRACTION_METHOD=.*/FACT_EXTRACTION_METHOD=rule_based/' .env
    sed -i 's/^ENABLE_ASYNC_PROCESSING=.*/ENABLE_ASYNC_PROCESSING=true/' .env
    sed -i 's/^ENABLE_MESSAGE_FILTERING=.*/ENABLE_MESSAGE_FILTERING=true/' .env
    sed -i 's/^CONVERSATION_WINDOW_SIZE=.*/CONVERSATION_WINDOW_SIZE=5/' .env
    sed -i 's/^MAX_CONCURRENT_WINDOWS=.*/MAX_CONCURRENT_WINDOWS=50/' .env
    sed -i 's/^MONITORING_WORKERS=.*/MONITORING_WORKERS=2/' .env
    sed -i 's/^HEALTH_CHECK_INTERVAL=.*/HEALTH_CHECK_INTERVAL=600/' .env
    sed -i 's/^USE_REDIS=.*/USE_REDIS=true/' .env
    sed -i 's/^REDIS_URL=.*/REDIS_URL=redis:\/\/redis:6379\/0/' .env
    
    echo "✅ Environment optimized for efficiency"
    echo "💾 Backup saved as .env.backup"
}

# Function to clean up old containers and volumes
cleanup() {
    echo "🧹 Cleaning up old containers and images"
    docker-compose down --remove-orphans
    docker system prune -f
    echo "✅ Cleanup complete"
}

# Function to build and start services
start_services() {
    echo "🚀 Building and starting services"
    docker-compose up --build -d
    
    # Wait for services to be healthy
    echo "⏳ Waiting for services to be healthy..."
    sleep 10
    
    # Check Redis health
    if docker-compose exec redis redis-cli ping > /dev/null 2>&1; then
        echo "✅ Redis is healthy"
    else
        echo "⚠️  Redis health check failed"
    fi
    
    # Check bot health
    if docker-compose logs bot | grep -q "Resource monitoring enabled\|Bot started"; then
        echo "✅ Bot appears to be starting"
    else
        echo "⚠️  Bot may have issues - check logs"
    fi
}

# Function to show logs
show_logs() {
    echo "📜 Showing recent logs (press Ctrl+C to exit)"
    docker-compose logs -f --tail=100
}

# Function to show health status
health_check() {
    echo "🩺 Health Check"
    echo "==============="
    
    # Check containers
    echo "📦 Container Status:"
    docker-compose ps
    echo ""
    
    # Check Redis
    echo "🔴 Redis Status:"
    if docker-compose exec redis redis-cli ping > /dev/null 2>&1; then
        echo "✅ Redis: Connected"
        echo "   Memory usage: $(docker-compose exec redis redis-cli info memory | grep used_memory_human | cut -d: -f2 | tr -d '\r')"
    else
        echo "❌ Redis: Not responding"
    fi
    echo ""
    
    # Check bot logs for recent errors
    echo "🤖 Bot Status:"
    recent_errors=$(docker-compose logs bot --tail=50 | grep -c "ERROR\|CRITICAL" || echo "0")
    recent_warnings=$(docker-compose logs bot --tail=50 | grep -c "WARNING" || echo "0")
    
    echo "   Recent errors: $recent_errors"
    echo "   Recent warnings: $recent_warnings"
    
    if [ "$recent_errors" -gt 5 ]; then
        echo "   ⚠️  High error rate detected"
    elif [ "$recent_errors" -gt 0 ]; then
        echo "   ⚠️  Some errors detected"
    else
        echo "   ✅ No recent errors"
    fi
    
    # Check CPU usage in logs
    cpu_critical=$(docker-compose logs bot --tail=20 | grep -c "CRITICAL: CPU usage" || echo "0")
    if [ "$cpu_critical" -gt 0 ]; then
        echo "   🔥 CPU pressure detected"
    else
        echo "   ✅ CPU usage normal"
    fi
}

# Function to show optimization recommendations
recommendations() {
    echo "💡 Optimization Recommendations"
    echo "==============================="
    echo ""
    echo "1. Monitor Resource Usage:"
    echo "   docker-compose logs bot | grep 'Resource usage'"
    echo ""
    echo "2. Check Redis Connection:"
    echo "   docker-compose exec redis redis-cli ping"
    echo ""
    echo "3. Monitor Processing Duration:"
    echo "   docker-compose logs bot | grep 'Duration.*ms'"
    echo ""
    echo "4. If CPU stays high (>90%):"
    echo "   - Set FACT_EXTRACTION_METHOD=rule_based"
    echo "   - Set ENABLE_PROFILE_SUMMARIZATION=false"
    echo "   - Reduce CONVERSATION_WINDOW_SIZE to 3"
    echo "   - Reduce MONITORING_WORKERS to 1"
    echo ""
    echo "5. If Memory is high (>80%):"
    echo "   - Reduce MAX_CONCURRENT_WINDOWS to 25"
    echo "   - Increase HEALTH_CHECK_INTERVAL to 900"
    echo "   - Set MAX_FACTS_PER_USER to 25"
    echo ""
    echo "6. Emergency mode (CPU >95% sustained):"
    echo "   - Set ENABLE_CONTINUOUS_MONITORING=false"
    echo "   - Restart with: docker-compose restart bot"
}

# Main menu
case "${1:-menu}" in
    "setup")
        check_docker
        check_env
        optimize_env
        cleanup
        start_services
        echo ""
        echo "🎉 Setup complete! Bot should be running optimally."
        echo "📊 Run './setup.sh health' to check status"
        echo "📜 Run './setup.sh logs' to view logs"
        ;;
    "logs")
        show_logs
        ;;
    "health")
        health_check
        ;;
    "optimize")
        optimize_env
        echo "🔄 Restart services to apply optimizations:"
        echo "   docker-compose restart bot"
        ;;
    "restart")
        echo "🔄 Restarting services"
        docker-compose restart
        health_check
        ;;
    "clean")
        cleanup
        ;;
    "recommendations")
        recommendations
        ;;
    "stop")
        echo "🛑 Stopping services"
        docker-compose down
        ;;
    "menu"|*)
        echo "Usage: $0 [command]"
        echo ""
        echo "Commands:"
        echo "  setup          - Complete setup with optimizations"
        echo "  logs           - Show live logs"
        echo "  health         - Check system health"
        echo "  optimize       - Apply performance optimizations"
        echo "  restart        - Restart services"
        echo "  clean          - Clean up containers and images"
        echo "  recommendations - Show optimization tips"
        echo "  stop           - Stop all services"
        echo ""
        echo "First time setup: $0 setup"
        ;;
esac