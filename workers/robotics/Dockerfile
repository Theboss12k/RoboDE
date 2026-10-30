FROM ros:jazzy-ros-base
RUN apt-get update && apt-get install -y --no-install-recommends ros-jazzy-moveit-py ros-jazzy-moveit-kinematics ros-jazzy-moveit-planners-ompl ros-jazzy-nav2-bringup ros-jazzy-nav2-simple-commander python3-venv && rm -rf /var/lib/apt/lists/*
RUN python3 -m venv --system-site-packages /opt/robode-env && /opt/robode-env/bin/pip install --no-cache-dir fastapi==0.159.1 uvicorn==0.54.0 httpx==0.28.1 pydantic==2.14.1 PyYAML==6.0.3 jsonschema==4.26.0 scipy==1.17.1 trimesh==4.11.2
WORKDIR /opt/robode
COPY SERVER_CLIENT/server ./SERVER_CLIENT/server
COPY workers/robotics ./workers/robotics
ENV ROS_LOG_DIR=/tmp/ros-log ROS_HOME=/tmp/ros-home PYTHONPYCACHEPREFIX=/tmp/pycache
ENV PYTHONPATH=/opt/robode/SERVER_CLIENT/server:/opt/robode ROS_DOMAIN_ID=93
EXPOSE 9120
ENTRYPOINT ["/ros_entrypoint.sh", "/opt/robode-env/bin/python", "-m", "uvicorn", "workers.robotics.server:app", "--host", "0.0.0.0", "--port", "9120"]
