var app = angular.module('djangoBMF', []);
app.config(function($locationProvider) {
    $locationProvider.html5Mode(true).hashPrefix('!');
});
app.config(function($httpProvider) {
    $httpProvider.defaults.headers.common['X-Requested-With'] = 'XMLHttpRequest';
});

app.directive('bmfContent', function() {
    return {
        template: '<h1>Test</h1><p>asdadasdasd</p>'
    };
});

// this controller is evaluated first, it gets all
// the data needed to access the bmf's views
app.controller('FrameworkCtrl', function($http, $window, $scope, $location) {

    $scope.django = $window.django;
    console.log($window.django);

    // TODO: MOVE TO FACTORY/SERVICE/ETC
    $scope.get_view = function(url) {
        if (url == undefined) {
            url = $location.path();
        }

        var current = null;
        $scope.BMFrameworkViewData.dashboards.forEach(function(d, dindex) {
            d.categories.forEach(function(c, cindex) {
                c.views.forEach(function(v, vindex) {
                    if (v.url == location.pathname) {
                        current = {
                            'view': v,
                            'category': c,
                            'dashboard': d
                        };
                    }
                });
            });
        });
        return current
    }

    $scope.$on('$locationChangeStart', function(event, next, current, ostate, nstate) {
        if (next == current) {
            return true;
        }
        console.log(event, next, current);

        if ($location.protocol() == 'http' && $location.port() == 80) {
            var prefix = 'http://'+ $location.host();
        }
        else if ($location.protocol() == 'https' && $location.port() == 443) {
            var prefix = 'https://'+ $location.host();
        }
        else {
            var prefix = $location.protocol() + '://' + $location.host() + ':' + $location.port()
        }

        // find if the url is managed by the framework
        var url = null;
        $scope.BMFrameworkViewData.dashboards.forEach(function(d, dindex) {
            d.categories.forEach(function(c, cindex) {
                c.views.forEach(function(v, vindex) {
                    if (prefix + v.url == next) {
                        url = v.api;
                    }
                });
            });
        });
        if (url) {
            $scope.$broadcast('BMFrameworkLoadView', url);
            return true;
        }

        // prevent the default action, when leaving to a page which is not managed
        // by the framework. using this will make the url reload on an history-back
        // event
        event.preventDefault(true);
        $window.location = next;
    });

    $scope.$on('BMFrameworkLoadView', function(event, url) {
        $http.get(url).then(function(response) {
            console.log('LOADVIEW', response, response.data.html);
        });
    });

    var url = $('body').data('api');
    $http.get(url).then(function(response) {
        $scope.BMFrameworkViewData = response.data;
        var current = $scope.get_view();
        $scope.$broadcast('BMFrameworkLoaded', current);
        if (current) {
            $scope.$broadcast('BMFrameworkLoadView', current.view.api);
        }
    });
});

// This controller updates the dashboard dropdown menu
app.controller('DashboardCtrl', function($scope) {
    $scope.$on('BMFrameworkLoaded', function(event, current_view) {

        $scope.load_dashboard = function(key) {
            $scope.$parent.$broadcast('BMFrameworkUpdateSidebar', key);
            $scope.$parent.$broadcast('BMFrameworkUpdateDashboard', key);
        };

        if (current_view) {
            $scope.load_dashboard(current_view.dashboard.key);
        }
        else {
            $scope.load_dashboard(null);
        }
    });

    $scope.$on('BMFrameworkUpdateDashboard', function(event, key) {
        var response = [];
        var current_dashboard = {};

        $scope.BMFrameworkViewData.dashboards.forEach(function(element, index) {
            var active = false
            if (key == element.key) {
                active = true
                current_dashboard = {
                    'key': element.key,
                    'name': element.name
                }
            }

            response.push({
                'key': element.key,
                'name': element.name,
                'active': active,
            });
        });

        $scope.data = response;
        $scope.current_dashboard = current_dashboard;
    });
});

// This controller updates the dashboard dropdown menu
app.controller('SidebarCtrl', function($scope) {
    $scope.$on('BMFrameworkUpdateSidebar', function(event, key) {

        current_view = $scope.get_view();

        var response = [];
        $scope.BMFrameworkViewData.dashboards.forEach(function(d, dindex) {
            if (key == d.key) {
                response.push({'class': 'sidebar-board', 'name': d.name});
                d.categories.forEach(function(c, cindex) {
                    response.push({'name': c.name});
                    c.views.forEach(function(v, vindex) {
                        if (current_view && c.key == current_view.category.key && v.key == current_view.view.key) {
                            response.push({'name': v.name, 'url': v.url, 'class': 'active'});
                            $scope.$parent.$broadcast('BMFrameworkUpdateView', v, c, d);
                        }
                        else {
                            response.push({'name': v.name, 'url': v.url});
                        }
                    });
                });
            }
        });
        $scope.data = response;
    });
});

app.controller('bmfListCtrl', function($scope, $http) {
    $scope.$on('BMFrameworkUpdateView', function(event, view, category, dashboard) {
        var url = view.dataapi + '?d=' + dashboard.key + '&c=' + category.key + '&v=' + view.key
        $http.get(url).then(function(response) {
            $scope.data = response.data;
        });
    });
});