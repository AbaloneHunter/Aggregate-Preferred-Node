#!/usr/bin/env python3
"""
GitHub Actions Node Selector
自动测试节点延迟、速度，并生成优选节点列表
"""

import os
import json
import time
import requests
import base64
import re
from datetime import datetime
from urllib.parse import urlparse
import concurrent.futures
import threading

class NodeSelector:
    def __init__(self):
        self.nodes_file = "Nodes"
        self.output_file = "Preferred-Node"
        self.results_file = "test-results.json"
        
        # 测试配置
        self.timeout = 10
        self.latency_threshold = 3000  # 延迟阈值(ms)
        self.max_workers = 3  # 最大并发数
        
        # 测试URL列表
        self.test_urls = [
            {
                'url': 'https://www.gstatic.com/generate_204',
                'name': 'Google Static',
                'expected_status': 204,
                'weight': 1.0
            },
            {
                'url': 'https://httpbin.org/get',
                'name': 'HttpBin', 
                'expected_status': 200,
                'weight': 0.9
            },
            {
                'url': 'https://www.cloudflare.com/cdn-cgi/trace',
                'name': 'Cloudflare',
                'expected_status': 200,
                'weight': 0.8
            },
            {
                'url': 'https://api.github.com',
                'name': 'GitHub',
                'expected_status': 200,
                'weight': 0.7
            }
        ]
        
        self.results = []
        self.lock = threading.Lock()
        
    def parse_nodes_file(self):
        """解析节点文件"""
        nodes = []
        if not os.path.exists(self.nodes_file):
            print(f"❌ 节点文件 {self.nodes_file} 不存在")
            return nodes
            
        try:
            with open(self.nodes_file, 'r', encoding='utf-8') as f:
                for line_num, line in enumerate(f, 1):
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    
                    node = self.parse_node_line(line)
                    if node:
                        nodes.append(node)
                    else:
                        print(f"⚠️ 第{line_num}行无法解析: {line[:50]}...")
                        
            print(f"✅ 解析到 {len(nodes)} 个节点")
            return nodes
            
        except Exception as e:
            print(f"❌ 读取节点文件失败: {e}")
            return []
    
    def parse_node_line(self, line):
        """解析单行节点配置"""
        line = line.strip()
        
        patterns = [
            # SSR格式
            {'regex': r'^ssr://([A-Za-z0-9+/=]+)', 'type': 'ssr'},
            # VMess格式  
            {'regex': r'^vmess://([A-Za-z0-9+/=]+)', 'type': 'vmess'},
            # Trojan格式
            {'regex': r'^trojan://([^@]+)@([^:]+):(\d+)', 'type': 'trojan'},
            # SS格式
            {'regex': r'^ss://([A-Za-z0-9+/=]+)', 'type': 'ss'},
            # HTTP代理
            {'regex': r'^http://([^:]+):(\d+)', 'type': 'http'},
            # SOCKS5代理
            {'regex': r'^socks5://([^:]+):(\d+)', 'type': 'socks5'},
            # 主机端口格式
            {'regex': r'^([^:]+):(\d+)$', 'type': 'host-port'}
        ]
        
        for pattern in patterns:
            match = re.match(pattern['regex'], line)
            if match:
                return {
                    'original': line,
                    'type': pattern['type'],
                    'parts': match.groups()
                }
        
        return None
    
    def extract_host_from_node(self, node):
        """从节点配置中提取主机地址"""
        try:
            if node['type'] in ['ssr', 'vmess', 'ss']:
                # Base64解码
                decoded = base64.b64decode(node['parts'][0] + '==').decode('utf-8', errors='ignore')
                
                # 尝试多种方式提取主机名
                host_patterns = [
                    r'"add":"([^"]+)"',      # VMess格式
                    r'server=([^&]+)',       # 参数格式
                    r'@([^:]+):',            # 用户信息格式
                    r'([a-zA-Z0-9.-]+\.[a-zA-Z]{2,})'  # 通用域名格式
                ]
                
                for pattern in host_patterns:
                    match = re.search(pattern, decoded)
                    if match:
                        return match.group(1)
                        
            elif node['type'] == 'trojan':
                return node['parts'][1]  # 主机名
            elif node['type'] in ['http', 'socks5', 'host-port']:
                return node['parts'][0]  # 主机名
                
        except Exception as e:
            print(f"⚠️ 提取主机地址失败: {e}")
            
        return None
    
    def test_latency(self, node):
        """测试节点延迟"""
        test_results = []
        fastest_success = None
        
        for test_url in self.test_urls:
            try:
                start_time = time.time()
                
                response = requests.get(
                    test_url['url'],
                    timeout=8,
                    headers={
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                    }
                )
                
                latency = int((time.time() - start_time) * 1000)  # 转换为毫秒
                is_success = response.status_code == test_url['expected_status']
                
                test_result = {
                    'url': test_url['name'],
                    'latency': latency,
                    'status': response.status_code,
                    'success': is_success,
                    'weight': test_url['weight']
                }
                
                test_results.append(test_result)
                
                # 记录最快成功测试
                if is_success and latency < self.latency_threshold:
                    if not fastest_success or latency < fastest_success['latency']:
                        fastest_success = test_result
                
                # 优质节点提前结束测试
                if latency < 100:
                    break
                    
                time.sleep(0.3)  # 短暂延迟
                
            except requests.RequestException as e:
                test_results.append({
                    'url': test_url['name'],
                    'latency': -1,
                    'status': 0,
                    'success': False,
                    'error': str(e),
                    'weight': test_url['weight']
                })
        
        return {
            'fastest_success': fastest_success,
            'all_results': test_results,
            'passed': fastest_success is not None
        }
    
    def test_download_speed(self, node, latency):
        """测试下载速度"""
        print(f"    🚀 开始速度测试，当前延迟: {latency}ms")
        
        # 根据延迟调整测试文件大小
        if latency < 200:
            file_size = 512000  # 500KB
        elif latency < 500:
            file_size = 256000  # 250KB
        else:
            file_size = 102400  # 100KB
        
        speed_test_urls = [
            f'https://httpbin.org/bytes/{file_size}',
            'https://speedtest.ftp.otenet.gr/files/test1Mb.db',
            'https://proof.ovh.net/files/1Mb.dat'
        ]
        
        for test_url in speed_test_urls:
            try:
                start_time = time.time()
                
                response = requests.get(
                    test_url,
                    timeout=15,
                    stream=True,
                    headers={
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                        'Cache-Control': 'no-cache'
                    }
                )
                response.raise_for_status()
                
                # 读取完整内容以确保测量准确
                content = b''
                for chunk in response.iter_content(chunk_size=8192):
                    content += chunk
                
                duration = time.time() - start_time
                data_size = len(content)
                
                if data_size > 0 and duration > 0:
                    speed_kbps = (data_size / duration) / 1024  # KB/s
                    speed_mbps = speed_kbps / 1024  # MB/s
                    
                    print(f"    📊 速度测试完成: {speed_kbps:.0f} KB/s ({speed_mbps:.2f} MB/s)")
                    return int(speed_kbps)
                    
            except requests.RequestException:
                continue
                
            time.sleep(0.5)
        
        print("    ⚠️ 所有测速URL均失败")
        return 0
    
    def get_geo_info(self):
        """获取地理位置信息"""
        try:
            # 获取公网IP
            ip_response = requests.get('https://httpbin.org/ip', timeout=8)
            if ip_response.status_code == 200:
                ip_data = ip_response.json()
                public_ip = ip_data.get('origin', '').split(',')[0]
                
                if public_ip:
                    # 获取地理位置
                    geo_response = requests.get(f'http://ip-api.com/json/{public_ip}', timeout=5)
                    if geo_response.status_code == 200:
                        geo_data = geo_response.json()
                        if geo_data.get('status') == 'success':
                            return {
                                'country': geo_data.get('country', 'Unknown'),
                                'city': geo_data.get('city', 'Unknown'),
                                'isp': geo_data.get('isp', 'Unknown'),
                                'lat': geo_data.get('lat'),
                                'lon': geo_data.get('lon'),
                                'ip': public_ip
                            }
        except requests.RequestException:
            pass
        
        return {
            'country': 'Unknown',
            'city': 'Unknown', 
            'isp': 'Unknown',
            'lat': None,
            'lon': None,
            'ip': 'Unknown'
        }
    
    def calculate_score(self, latency, speed, success):
        """计算综合评分"""
        if latency <= 0:
            return 0
        
        # 延迟评分
        if latency < 50:
            latency_score = 100
        elif latency < 100:
            latency_score = 95
        elif latency < 200:
            latency_score = 85
        elif latency < 300:
            latency_score = 75
        elif latency < 500:
            latency_score = 60
        elif latency < 1000:
            latency_score = 40
        else:
            latency_score = 20
        
        # 速度评分
        if speed == 0:
            speed_score = 0
        elif speed > 10000:
            speed_score = 100
        elif speed > 5000:
            speed_score = 90
        elif speed > 2000:
            speed_score = 80
        elif speed > 1000:
            speed_score = 70
        elif speed > 500:
            speed_score = 60
        elif speed > 100:
            speed_score = 40
        else:
            speed_score = 20
        
        # 成功率评分
        success_score = 100 if success else 0
        
        # 加权评分
        total_score = (latency_score * 0.5 + speed_score * 0.3 + success_score * 0.2)
        return round(total_score, 1)
    
    def test_single_node(self, node, index, total_count):
        """测试单个节点"""
        node_id = f"{index+1}/{total_count}"
        print(f"\n🔍 测试节点 {node_id}: {node['type']}节点")
        print(f"    📝 配置: {node['original'][:80]}...")
        
        try:
            # 第一步：延迟测试
            latency_test = self.test_latency(node)
            
            if not latency_test['passed']:
                print(f"    ❌ 未通过延迟测试，跳过测速")
                result = {
                    'node': node['original'],
                    'type': node['type'],
                    'latency': 'Timeout',
                    'speed': 'Not Tested',
                    'country': 'Unknown',
                    'city': 'Unknown',
                    'isp': 'Unknown',
                    'ip': 'Unknown',
                    'score': 0,
                    'success': False,
                    'test_url': 'None',
                    'timestamp': datetime.now().isoformat(),
                    'skipped_speed_test': True
                }
                return result
            
            latency = latency_test['fastest_success']['latency']
            print(f"    ✅ 延迟测试通过: {latency}ms")
            
            # 第二步：获取地理位置
            geo_info = self.get_geo_info()
            print(f"    🌍 地理位置: {geo_info['country']}/{geo_info['city']} ({geo_info['isp']})")
            
            # 第三步：速度测试
            speed = 0
            if latency < self.latency_threshold:
                speed = self.test_download_speed(node, latency)
            else:
                print(f"    ⚠️ 延迟过高 ({latency}ms)，跳过测速")
            
            # 第四步：计算评分
            score = self.calculate_score(latency, speed, latency_test['fastest_success']['success'])
            
            result = {
                'node': node['original'],
                'type': node['type'],
                'latency': latency,
                'speed': f"{speed} KB/s" if speed > 0 else "Failed",
                'country': geo_info['country'],
                'city': geo_info['city'],
                'isp': geo_info['isp'],
                'ip': geo_info['ip'],
                'score': score,
                'success': latency_test['fastest_success']['success'],
                'test_url': latency_test['fastest_success']['url'],
                'timestamp': datetime.now().isoformat()
            }
            
            print(f"    📊 综合评分: {score}")
            return result
            
        except Exception as e:
            print(f"    ❌ 测试失败: {e}")
            return None
    
    def run_tests(self):
        """运行所有测试"""
        print("🚀 开始节点测试...")
        print(f"📡 测试URL: {[u['name'] for u in self.test_urls]}")
        print(f"⏱️ 延迟阈值: {self.latency_threshold}ms")
        print(f"🔢 最大并发数: {self.max_workers}\n")
        
        nodes = self.parse_nodes_file()
        if not nodes:
            print("❌ 没有找到可测试的节点")
            return
        
        print(f"📊 总共 {len(nodes)} 个节点需要测试\n")
        
        passed_count = 0
        speed_tested_count = 0
        
        # 使用线程池并发测试
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_node = {
                executor.submit(self.test_single_node, node, i, len(nodes)): (i, node)
                for i, node in enumerate(nodes)
            }
            
            for future in concurrent.futures.as_completed(future_to_node):
                i, node = future_to_node[future]
                try:
                    result = future.result()
                    if result:
                        with self.lock:
                            self.results.append(result)
                            
                            if result['success']:
                                passed_count += 1
                                if result['speed'] not in ['Not Tested', 'Failed']:
                                    speed_tested_count += 1
                
                except Exception as e:
                    print(f"❌ 节点测试异常: {e}")
        
        # 按评分排序
        self.results.sort(key=lambda x: x['score'], reverse=True)
        
        # 保存结果
        self.save_test_results(passed_count, speed_tested_count, len(nodes))
    
    def save_test_results(self, passed_count, speed_tested_count, total_count):
        """保存测试结果"""
        output_data = {
            'timestamp': datetime.now().isoformat(),
            'total_tested': total_count,
            'passed_latency_test': passed_count,
            'speed_tested': speed_tested_count,
            'preferred_nodes': [r for r in self.results if r['score'] > 0][:20],
            'all_results': self.results,
            'test_config': {
                'urls': self.test_urls,
                'timeout': self.timeout,
                'latency_threshold': self.latency_threshold
            }
        }
        
        with open(self.results_file, 'w', encoding='utf-8') as f:
            json.dump(output_data, f, indent=2, ensure_ascii=False)
        
        print('\n🎉 测试完成!')
        print(f"📊 总测试节点: {total_count}")
        print(f"✅ 通过延迟测试: {passed_count}")
        print(f"🚀 完成速度测试: {speed_tested_count}")
        print(f"🏆 最佳节点评分: {self.results[0]['score'] if self.results else 'N/A'}")
    
    def generate_preferred_node_file(self):
        """生成优选节点文件"""
        try:
            with open(self.results_file, 'r', encoding='utf-8') as f:
                test_data = json.load(f)
            
            output = f"""# 🚀 Preferred Nodes - 优选节点
# Generated: {datetime.fromisoformat(test_data['timestamp']).strftime('%Y-%m-%d %H:%M:%S')}
# Total nodes tested: {test_data['total_tested']}
# Passed latency test: {test_data['passed_latency_test']}
# Speed tested: {test_data['speed_tested']}
# Success rate: {(test_data['passed_latency_test'] / test_data['total_tested'] * 100):.1f}%

# 🏆 Top Recommended Nodes (推荐节点)
# Format: 评分 | 延迟 | 速度 | 位置 | 运营商
# Score | Latency | Speed | Location | ISP

"""
            
            # 只显示有速度测试结果的节点
            valid_nodes = [
                node for node in test_data['preferred_nodes'] 
                if node['speed'] not in ['Not Tested', 'Failed'] and node['score'] > 0
            ]
            
            for i, node in enumerate(valid_nodes):
                status = '✅' if node['success'] else '⚠️'
                speed_value = int(node['speed'].split()[0]) if 'KB/s' in node['speed'] else 0
                speed_mbps = speed_value / 1024
                
                output += f"""# {status} {i+1}. 评分:{node['score']} | 延迟:{node['latency']}ms | 速度:{speed_mbps:.1f} MB/s | {node['country']} | {node['isp']}
{node['node']}

"""
            
            if not valid_nodes:
                output += "# ❌ 没有找到合格的节点，请检查节点配置或网络连接\n\n"
            
            output += f"# 📊 All Tested Nodes (所有测试节点)\n"
            output += f"# Total: {len(test_data['all_results']} nodes\n\n"
            
            for i, node in enumerate(test_data['all_results']):
                status = '✅' if node['success'] else '❌'
                speed_info = node['speed'] if node['speed'] != 'Not Tested' else '未测速'
                output += f"# {status} {i+1}. 评分:{node['score']} 延迟:{node['latency']}ms 速度:{speed_info} {node['country']}\n"
                output += f"{node['node']}\n"
                
                if (i + 1) % 10 == 0:
                    output += '\n'
            
            # 添加统计信息
            valid_latencies = [
                node['latency'] for node in test_data['all_results'] 
                if node['latency'] != 'Timeout' and isinstance(node['latency'], (int, float))
            ]
            
            output += f"\n# 📈 Statistics (统计信息)\n"
            output += f"# Successful nodes: {test_data['passed_latency_test']}\n"
            output += f"# Speed tested nodes: {test_data['speed_tested']}\n"
            
            avg_score = sum(node['score'] for node in test_data['all_results']) / len(test_data['all_results'])
            output += f"# Average score: {avg_score:.1f}\n"
            
            if valid_latencies:
                output += f"# Best latency: {min(valid_latencies)}ms\n"
                output += f"# Average latency: {sum(valid_latencies) / len(valid_latencies):.1f}ms\n"
            
            with open(self.output_file, 'w', encoding='utf-8') as f:
                f.write(output)
            
            print(f"✅ {self.output_file} 文件已生成")
            
        except Exception as e:
            print(f"❌ 生成结果文件失败: {e}")

def main():
    """主函数"""
    print("=" * 60)
    print("GitHub Actions Node Selector")
    print("节点优选器 v1.0")
    print("=" * 60)
    
    selector = NodeSelector()
    
    # 运行测试
    selector.run_tests()
    
    # 生成结果文件
    selector.generate_preferred_node_file()
    
    print("\n🎊 所有任务完成!")

if __name__ == "__main__":
    main()
