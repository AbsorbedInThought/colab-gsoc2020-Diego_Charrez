from __future__ import absolute_import, division, print_function

import base64
import imageio
import matplotlib
import matplotlib.pyplot as plt
import numpy as np

import tensorflow as tf

from args import dqn_args_train
from tf_agents.agents.dqn import dqn_agent
from tf_agents.drivers import dynamic_step_driver
from tf_agents.environments import suite_gym
from tf_agents.environments import tf_py_environment
from tf_agents.eval import metric_utils
from tf_agents.metrics import tf_metrics
from tf_agents.networks import q_network
from tf_agents.policies import random_tf_policy
from tf_agents.replay_buffers import tf_uniform_replay_buffer
from tf_agents.trajectories import trajectory
from tf_agents.utils import common

# Enables TensorFlow 2 behaviors.
tf.compat.v1.enable_v2_behavior()


def compute_avg_return(environment, policy, num_episodes):
    """Computes the average return.
    
    Args:
        environment: The environment.
        policy: The agent's policy.
        num_episodes: Number of episodes.
        
    Returns:
        avg_return: The average return.
    """

    total_return = 0.0
    for _ in range(num_episodes):
        time_step = environment.reset()
        episode_return = 0.0
        
        while not time_step.is_last():
            action_step = policy.action(time_step)
            time_step = environment.step(action_step.action)
            episode_return += time_step.reward
        total_return += episode_return

    avg_return = total_return / num_episodes
    return avg_return.numpy()[0]


def collect_step(environment, policy, buffer):
    """ Collects data from one step and stores it in the replay buffer.
    
    Args:
        environment: The environment.
        policy: The agent's policy.
        buffer: The replay buffer.
        
    Yields:
        A trajectory added to the replay buffer.
    """
        
    time_step = environment.current_time_step()
    action_step = policy.action(time_step)
    next_time_step = environment.step(action_step.action)
    traj = trajectory.from_transition(time_step, action_step, next_time_step)

    buffer.add_batch(traj)

def collect_data(environment, policy, buffer, n_steps):
    """ Collects data from n steps and stores it in the replay buffer.
    
    Args:
        environment: The environment.
        policy: The agent's policy.
        buffer: The replay buffer.
        n_steps: The number of steps to collect data.
        
    Yields:
        n_steps added to the replay buffer.
    """
    for _ in range(n_steps):
        collect_step(environment, policy, buffer)    
    
def main():
    args = dqn_args_train()

    # Set the random seed.
    if args.seed is not None:
        np.random.seed(args.seed)
        tf.random.set_seed(args.seed)
        
    # Create the environment
    env_name = "CartPole-v0"
    env = suite_gym.load(env_name)
    env.reset()
    
    train_py_env = suite_gym.load(env_name)
    eval_py_env = suite_gym.load(env_name)
    train_env = tf_py_environment.TFPyEnvironment(train_py_env)
    eval_env = tf_py_environment.TFPyEnvironment(eval_py_env)
    
    # Create Q Network
    fc_layer_params = (100,)
    q_net = q_network.QNetwork(
        train_env.observation_spec(),
        train_env.action_spec(),
        fc_layer_params=fc_layer_params)


    optimizer = tf.compat.v1.train.AdamOptimizer(learning_rate=args.learning_rate)

    train_step_counter = tf.Variable(0)

    # Create the agent
    agent = dqn_agent.DqnAgent(
        train_env.time_step_spec(),
        train_env.action_spec(),
        q_network=q_net,
        optimizer=optimizer,
        td_errors_loss_fn=common.element_wise_squared_loss,
        train_step_counter=train_step_counter)
    
    agent.initialize()
    
    # Create policies
    eval_policy = agent.policy
    collect_policy = agent.collect_policy
    random_policy = random_tf_policy.RandomTFPolicy(train_env.time_step_spec(),
                                                train_env.action_spec())
    
    replay_buffer = tf_uniform_replay_buffer.TFUniformReplayBuffer(
        data_spec=agent.collect_data_spec,
        batch_size=train_env.batch_size,
        max_length=args.replay_buffer_max_length)
    
    collect_data(train_env, random_policy, replay_buffer, n_steps=args.initial_collect_steps)

    dataset = replay_buffer.as_dataset(
        num_parallel_calls=3, 
        sample_batch_size=args.batch_size, 
        num_steps=2).prefetch(3)
    
    iterator = iter(dataset)

    
    # (Optional) Optimize by wrapping some of the code in a graph using TF function.
    agent.train = common.function(agent.train)

    # Reset the train step
    agent.train_step_counter.assign(0)

    # Evaluate the agent's policy once before training.
    avg_return = compute_avg_return(eval_env, agent.policy, args.num_eval_episodes)
    returns = [avg_return]

    for _ in range(args.num_iterations):

        # Collect a few steps using collect_policy and save to the replay buffer.
        for _ in range(args.collect_steps_per_iteration):
            collect_step(train_env, agent.collect_policy, replay_buffer)

        # Sample a batch of data from the buffer and update the agent's network.
        experience, unused_info = next(iterator)
        train_loss = agent.train(experience).loss

        step = agent.train_step_counter.numpy()

        if step % args.log_interval == 0:
            print('step = {0}: loss = {1}'.format(step, train_loss))

        if step % args.eval_interval == 0:
            avg_return = compute_avg_return(eval_env, agent.policy, args.num_eval_episodes)
            print('step = {0}: Average Return = {1}'.format(step, avg_return))
            returns.append(avg_return)


if __name__ == '__main__':
    main()
